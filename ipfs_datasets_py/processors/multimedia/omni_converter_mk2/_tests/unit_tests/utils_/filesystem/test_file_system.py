import unittest
from unittest.mock import Mock, MagicMock
import os

# Make sure the input file and documentation file exist.
cwd = os.getcwd()
assert os.path.exists(f'{cwd}/utils/filesystem.py'), "utils/filesystem.py does not exist at the specified directory."
assert os.path.exists(f'{cwd}/utils/filesystem_stubs.md'), "Documentation for utils/filesystem.py does not exist at the specified directory."

from utils.filesystem import FileSystem, FileContent, FileInfo

from datetime import datetime
import tempfile
import os
import stat
from pathlib import Path


class TestFileSystemFileExists(unittest.TestCase):
    """Test FileSystem.file_exists static method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []
        self.temp_dirs = []

    def tearDown(self):
        """Clean up test fixtures."""
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

    def test_file_exists_with_existing_file(self):
        """
        GIVEN path to an existing file
        WHERE:
            - existing_file = temporary file created for test
        WHEN file_exists is called
        THEN expect:
            - Return value == True
        """
        existing_file = self._create_temp_file()
        
        result = FileSystem.file_exists(existing_file)
        
        self.assertTrue(result)

    def test_file_exists_with_nonexistent_file(self):
        """
        GIVEN path to a file that does not exist
        WHERE:
            - nonexistent_file = "/definitely/does/not/exist.txt"
        WHEN file_exists is called
        THEN expect:
            - Return value == False
        """
        nonexistent_file = "/definitely/does/not/exist.txt"
        
        result = FileSystem.file_exists(nonexistent_file)
        
        self.assertFalse(result)

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
        
        self.assertFalse(result)

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
        
        self.assertTrue(result)

    def test_file_exists_with_absolute_path(self):
        """
        GIVEN absolute path to an existing file
        WHERE:
            - absolute_path = full system path to test file
        WHEN file_exists is called
        THEN expect:
            - Return value == True
            - Absolute path handled without errors
        """
        temp_file = self._create_temp_file()
        absolute_path = os.path.abspath(temp_file)
        
        result = FileSystem.file_exists(absolute_path)
        
        self.assertTrue(result)

    def test_file_exists_with_empty_string_path(self):
        """
        GIVEN empty string as file path
        WHERE:
            - empty_string_path = ""
        WHEN file_exists is called
        THEN expect:
            - Return value == False
            - No exceptions raised
        """
        empty_string_path = ""
        
        result = FileSystem.file_exists(empty_string_path)
        
        self.assertFalse(result)

    def test_file_exists_with_none_path(self):
        """
        GIVEN None as file path parameter
        WHERE:
            - none_path = None
        WHEN file_exists is called
        THEN expect TypeError to be raised
        """
        none_path = None
        
        with self.assertRaises(TypeError):
            FileSystem.file_exists(none_path)

    def test_file_exists_with_permission_denied_file(self):
        """
        GIVEN file that exists but is in a directory with restricted permissions
        WHERE:
            - permission_denied_file = file in directory with no execute permissions
        WHEN file_exists is called
        THEN expect:
            - Return value == False (cannot access file to verify existence)
            - No exceptions raised
        """
        # Create a directory and file
        temp_dir = tempfile.mkdtemp()
        self.temp_dirs.append(temp_dir)
        
        temp_file_path = os.path.join(temp_dir, "test_file.txt")
        with open(temp_file_path, 'w') as f:
            f.write("test content")
        
        # Remove execute permissions from directory
        os.chmod(temp_dir, 0o600)  # read/write but no execute
        
        try:
            result = FileSystem.file_exists(temp_file_path)
            # Should return False since we can't access the file
            self.assertFalse(result)
        finally:
            # Restore permissions for cleanup
            os.chmod(temp_dir, 0o755)
            os.unlink(temp_file_path)

    def test_file_exists_with_symlink_to_existing_file(self):
        """
        GIVEN symbolic link pointing to an existing file
        WHERE:
            - symlink_to_existing = symbolic link pointing to real file
        WHEN file_exists is called on the symlink path
        THEN expect:
            - Return value == True
            - Symlink is followed to target file
        """
        # Create target file
        target_file = self._create_temp_file()
        
        # Create symlink
        symlink_path = target_file + "_symlink"
        os.symlink(target_file, symlink_path)
        self.temp_files.append(symlink_path)
        
        result = FileSystem.file_exists(symlink_path)
        
        self.assertTrue(result)

    def test_file_exists_with_symlink_to_nonexistent_file(self):
        """
        GIVEN symbolic link pointing to a nonexistent file (broken symlink)
        WHERE:
            - broken_symlink = symbolic link pointing to nonexistent target
        WHEN file_exists is called on the symlink path
        THEN expect:
            - Return value == False
            - Broken symlink treated as nonexistent file
        """
        # Create symlink to nonexistent file
        nonexistent_target = "/path/that/does/not/exist.txt"
        symlink_path = tempfile.mktemp() + "_broken_symlink"
        os.symlink(nonexistent_target, symlink_path)
        self.temp_files.append(symlink_path)
        
        result = FileSystem.file_exists(symlink_path)
        
        self.assertFalse(result)


class TestFileSystemCreateDirectory(unittest.TestCase):
    """Test FileSystem.create_directory static method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []
        self.temp_dirs = []

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except OSError:
                pass
        
        # Clean up temporary directories (in reverse order for nested dirs)
        for temp_dir in reversed(self.temp_dirs):
            try:
                if os.path.exists(temp_dir):
                    # Restore permissions before removal
                    os.chmod(temp_dir, 0o755)
                    os.rmdir(temp_dir)
            except OSError:
                pass

    def test_create_directory_new_directory(self):
        """
        GIVEN path to a directory that does not exist
        AND parent directory exists and is writable
        WHERE:
            - new_directory = "/tmp/test_new_dir"
            - parent directory exists and is writable
        WHEN create_directory is called
        THEN expect:
            - Return value == True
            - Directory is created at specified path
            - Directory has standard permissions (755)
        """
        new_directory = os.path.join(tempfile.gettempdir(), "test_new_dir_" + str(os.getpid()))
        self.temp_dirs.append(new_directory)
        
        # Ensure directory doesn't exist
        self.assertFalse(os.path.exists(new_directory))
        
        result = FileSystem.create_directory(new_directory)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(new_directory))
        self.assertTrue(os.path.isdir(new_directory))
        
        # Check permissions (may vary by system)
        stat_info = os.stat(new_directory)
        mode = stat.S_IMODE(stat_info.st_mode)
        # Should have at least read/write/execute for owner
        self.assertTrue(mode & stat.S_IRUSR)
        self.assertTrue(mode & stat.S_IWUSR)
        self.assertTrue(mode & stat.S_IXUSR)

    def test_create_directory_already_exists(self):
        """
        GIVEN path to a directory that already exists
        WHERE:
            - existing_directory = path to directory that already exists
        WHEN create_directory is called
        THEN expect:
            - Return value == True (operation succeeds, directory exists)
            - No errors raised
            - Existing directory remains at original state
        """
        existing_directory = tempfile.mkdtemp()
        self.temp_dirs.append(existing_directory)
        
        # Verify directory exists
        self.assertTrue(os.path.exists(existing_directory))
        original_stat = os.stat(existing_directory)
        
        result = FileSystem.create_directory(existing_directory)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(existing_directory))
        
        # Verify directory remains unchanged
        current_stat = os.stat(existing_directory)
        self.assertEqual(original_stat.st_mtime, current_stat.st_mtime)

    def test_create_directory_nested_path_parents_exist(self):
        """
        GIVEN path to nested directory where all parent directories exist
        WHERE:
            - nested_path_parents_exist = "/tmp/existing/new_subdir"
            - /tmp/existing already exists
        WHEN create_directory is called
        THEN expect:
            - Return value == True
            - Nested directory is created without errors
            - Parent directories remain at original state
        """
        parent_dir = tempfile.mkdtemp()
        self.temp_dirs.append(parent_dir)
        
        nested_directory = os.path.join(parent_dir, "new_subdir")
        self.temp_dirs.append(nested_directory)
        
        # Ensure parent exists but nested doesn't
        self.assertTrue(os.path.exists(parent_dir))
        self.assertFalse(os.path.exists(nested_directory))
        
        result = FileSystem.create_directory(nested_directory)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(nested_directory))
        self.assertTrue(os.path.isdir(nested_directory))

    def test_create_directory_nested_path_parents_missing_returns_false(self):
        """
        GIVEN path to nested directory where parent directories do not exist
        WHERE:
            - nested_path_parents_missing = "/tmp/missing/path/new_dir"
            - /tmp/missing does not exist
        WHEN create_directory is called
        THEN expect:
            - Return value == False (non-recursive implementation)
        """
        temp_base = tempfile.gettempdir()
        missing_path = os.path.join(temp_base, "missing_" + str(os.getpid()))
        nested_path = os.path.join(missing_path, "path", "new_dir")
        
        # Ensure the path doesn't exist
        self.assertFalse(os.path.exists(missing_path))
        
        result = FileSystem.create_directory(nested_path)
        
        self.assertFalse(result)

    def test_create_directory_nested_path_parents_missing_no_nested_directory_created(self):
        """
        GIVEN path to nested directory where parent directories do not exist
        WHERE:
            - nested_path_parents_missing = "/tmp/missing/path/new_dir"
            - /tmp/missing does not exist
        WHEN create_directory is called
        THEN expect:
            - No nested directory created
        """
        temp_base = tempfile.gettempdir()
        missing_path = os.path.join(temp_base, "missing_" + str(os.getpid()))
        nested_path = os.path.join(missing_path, "path", "new_dir")
        
        # Ensure the path doesn't exist
        self.assertFalse(os.path.exists(missing_path))
        
        FileSystem.create_directory(nested_path)
        
        self.assertFalse(os.path.exists(nested_path))

    def test_create_directory_nested_path_parents_missing_no_parent_directory_created(self):
        """
        GIVEN path to nested directory where parent directories do not exist
        WHERE:
            - nested_path_parents_missing = "/tmp/missing/path/new_dir"
            - /tmp/missing does not exist
        WHEN create_directory is called
        THEN expect:
            - No parent directories created
        """
        temp_base = tempfile.gettempdir()
        missing_path = os.path.join(temp_base, "missing_" + str(os.getpid()))
        nested_path = os.path.join(missing_path, "path", "new_dir")
        
        # Ensure the path doesn't exist
        self.assertFalse(os.path.exists(missing_path))
        
        FileSystem.create_directory(nested_path)
        
        self.assertFalse(os.path.exists(missing_path))

    def test_create_directory_permission_denied(self):
        """
        GIVEN path to directory in location with restricted write permissions
        WHERE:
            - permission_denied_path = path in directory with no write permissions
        WHEN create_directory is called
        THEN expect:
            - Return value == False (graceful failure)
            - No PermissionError raised (errors handled internally)
            - No directory created
        """
        # Create a parent directory and restrict its permissions
        parent_dir = tempfile.mkdtemp()
        self.temp_dirs.append(parent_dir)
        
        # Remove write permissions
        os.chmod(parent_dir, 0o555)  # read and execute only
        
        restricted_path = os.path.join(parent_dir, "restricted_dir")
        
        try:
            result = FileSystem.create_directory(restricted_path)
            
            self.assertFalse(result)
            self.assertFalse(os.path.exists(restricted_path))
        finally:
            # Restore permissions for cleanup
            os.chmod(parent_dir, 0o755)

    def test_create_directory_file_exists_at_path(self):
        """
        GIVEN path where a file already exists (not a directory)
        WHERE:
            - file_exists_at_path = path where file (not directory) exists
        WHEN create_directory is called
        THEN expect:
            - Return value == False
            - Existing file remains at original state
            - No directory created
        """
        # Create a file
        fd, file_path = tempfile.mkstemp()
        os.close(fd)
        self.temp_files.append(file_path)
        
        # Write some content to verify file remains unchanged
        with open(file_path, 'w') as f:
            f.write("test content")
        
        original_stat = os.stat(file_path)
        
        result = FileSystem.create_directory(file_path)
        
        self.assertFalse(result)
        self.assertTrue(os.path.isfile(file_path))
        self.assertFalse(os.path.isdir(file_path))
        
        # Verify file content unchanged
        with open(file_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "test content")
        
        current_stat = os.stat(file_path)
        self.assertEqual(original_stat.st_size, current_stat.st_size)

    def test_create_directory_empty_string_path(self):
        """
        GIVEN empty string as directory path
        WHERE:
            - empty_string_path = ""
        WHEN create_directory is called
        THEN expect:
            - Return value == False
            - No directory created
        """
        empty_string_path = ""
        
        result = FileSystem.create_directory(empty_string_path)
        
        self.assertFalse(result)

    def test_create_directory_none_path(self):
        """
        GIVEN None as directory path parameter
        WHERE:
            - none_path = None
        WHEN create_directory is called
        THEN expect TypeError to be raised
        """
        none_path = None
        
        with self.assertRaises(TypeError):
            FileSystem.create_directory(none_path)

    def test_create_directory_relative_path(self):
        """
        GIVEN relative path to new directory
        WHERE:
            - relative_path = "./new_dir"
        WHEN create_directory is called
        THEN expect:
            - Return value == True
            - Directory created relative to current working directory
        """
        relative_path = "./new_test_dir_" + str(os.getpid())
        self.temp_dirs.append(relative_path)
        
        # Ensure directory doesn't exist
        self.assertFalse(os.path.exists(relative_path))
        
        result = FileSystem.create_directory(relative_path)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(relative_path))
        self.assertTrue(os.path.isdir(relative_path))

    def test_create_directory_absolute_path(self):
        """
        GIVEN absolute path to new directory
        WHERE:
            - absolute_path = full system path for new directory
        WHEN create_directory is called
        THEN expect:
            - Return value == True
            - Directory created at absolute path location
        """
        absolute_path = os.path.join(tempfile.gettempdir(), "abs_test_dir_" + str(os.getpid()))
        absolute_path = os.path.abspath(absolute_path)
        self.temp_dirs.append(absolute_path)
        
        # Ensure directory doesn't exist
        self.assertFalse(os.path.exists(absolute_path))
        
        result = FileSystem.create_directory(absolute_path)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(absolute_path))
        self.assertTrue(os.path.isdir(absolute_path))



class TestFileSystemReadFile(unittest.TestCase):
    """Test FileSystem.read_file static method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []
        self.temp_dirs = []

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    # Restore permissions before deletion
                    os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
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

    def _create_temp_file(self, content, mode="w", suffix=".txt"):
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

    def test_read_file_existing_text_file_binary_mode(self):
        """
        GIVEN existing text file with known content
        AND default mode 'rb'
        WHERE:
            - existing_text_file = temporary file with known text content
            - default_mode = "rb"
        WHEN read_file is called
        THEN expect:
            - FileContent instance returned
            - raw_content contains file bytes matching original content
            - File content == expected byte content
            - MIME type detected as text type
        """
        test_content = "Hello, World! Testing file read."
        temp_file = self._create_temp_file(test_content)
        
        file_content = FileSystem.read_file(temp_file)
        
        self.assertIsInstance(file_content, FileContent)
        self.assertEqual(file_content.as_binary, test_content.encode('utf-8'))
        self.assertTrue(file_content.mime_type.startswith("text/"))

    def test_read_file_existing_binary_file(self):
        """
        GIVEN existing binary file and default binary mode
        WHERE:
            - existing_binary_file = temporary file with binary data (e.g., image bytes)
            - default_mode = "rb"
        WHEN read_file is called
        THEN expect:
            - FileContent instance returned
            - raw_content contains binary data matching original
            - MIME type detected as binary type
        """
        binary_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'  # PNG header
        temp_file = self._create_temp_file(binary_content, mode="wb", suffix=".png")
        
        file_content = FileSystem.read_file(temp_file)
        
        self.assertIsInstance(file_content, FileContent)
        self.assertEqual(file_content.as_binary, binary_content)
        self.assertEqual(file_content.mime_type, "image/png")

    def test_read_file_with_text_mode(self):
        """
        GIVEN existing text file
        AND mode parameter set to text
        WHERE:
            - existing_text_file = temporary file with known text content
            - text_mode = "rt" or "r"
        WHEN read_file is called
        THEN expect:
            - FileContent instance returned
            - Content handled for text mode specifications
            - Encoding detected/applied per text mode rules
        """
        test_content = "Hello, World! Testing text mode."
        temp_file = self._create_temp_file(test_content)
        
        file_content = FileSystem.read_file(temp_file, mode="r")
        
        self.assertIsInstance(file_content, FileContent)
        self.assertEqual(file_content.as_binary, test_content.encode('utf-8'))

    def test_read_file_nonexistent_file(self):
        """
        GIVEN path to file that does not exist
        WHERE:
            - nonexistent_file = "/path/that/does/not/exist.txt"
        WHEN read_file is called
        THEN expect FileNotFoundError to be raised
        """
        nonexistent_file = "/path/that/does/not/exist.txt"
        
        with self.assertRaises(FileNotFoundError):
            FileSystem.read_file(nonexistent_file)

    def test_read_file_permission_denied(self):
        """
        GIVEN file that exists but cannot be read due to permissions
        WHERE:
            - permission_denied_file = file with no read permissions
        WHEN read_file is called
        THEN expect PermissionError to be raised
        """
        temp_file = self._create_temp_file("test content")
        
        # Remove read permissions
        os.chmod(temp_file, 0o000)
        
        with self.assertRaises(PermissionError):
            FileSystem.read_file(temp_file)

    def test_read_file_directory_path(self):
        """
        GIVEN path pointing to a directory instead of a file
        WHERE:
            - directory_path = path to existing directory
        WHEN read_file is called
        THEN expect IsADirectoryError to be raised
        """
        directory_path = tempfile.mkdtemp()
        self.temp_dirs.append(directory_path)
        
        with self.assertRaises(IsADirectoryError):
            FileSystem.read_file(directory_path)

    def test_read_file_empty_file(self):
        """
        GIVEN existing but empty file (0 bytes)
        WHERE:
            - empty_file = file with 0 bytes
        WHEN read_file is called
        THEN expect:
            - FileContent instance returned
            - raw_content == b""
            - size attribute == 0
        """
        temp_file = self._create_temp_file("")
        
        file_content = FileSystem.read_file(temp_file)
        
        self.assertIsInstance(file_content, FileContent)
        self.assertEqual(file_content.as_binary, b"")
        self.assertEqual(file_content.size, 0)

    def test_read_file_large_file(self):
        """
        GIVEN large file (10MB of repeated data)
        WHERE:
            - large_file = file containing 10MB of data
        WHEN read_file is called
        THEN expect:
            - FileContent instance returned without exceptions
            - All content read (verified by size attribute == 10MB)
            - Memory usage stays within set boundaries (no memory leaks)
        """
        # Create 10MB of data
        large_content = "x" * (10 * 1024 * 1024)  # 10MB
        temp_file = self._create_temp_file(large_content)
        
        file_content = FileSystem.read_file(temp_file)
        
        self.assertIsInstance(file_content, FileContent)
        self.assertEqual(file_content.size, 10 * 1024 * 1024)
        self.assertEqual(len(file_content.as_binary), 10 * 1024 * 1024)
        self.assertEqual(file_content.as_binary, large_content.encode('utf-8'))

    def test_read_file_invalid_mode(self):
        """
        GIVEN existing file
        AND invalid mode parameter
        WHERE:
            - existing_text_file = temporary file
            - invalid_mode = "invalid"
        WHEN read_file is called
        THEN expect ValueError to be raised
        """
        temp_file = self._create_temp_file("test content")
        
        with self.assertRaises(ValueError):
            FileSystem.read_file(temp_file, mode="invalid")

    def test_read_file_relative_path(self):
        """
        GIVEN existing file at relative path
        WHERE:
            - relative_path = "./test_file.txt"
            - file exists at relative location
        WHEN read_file is called
        THEN expect:
            - FileContent instance returned
            - File read from relative location without errors
        """
        test_content = "Relative path test content"
        temp_file = self._create_temp_file(test_content)
        relative_path = "./" + os.path.basename(temp_file)
        
        # Create file at relative path
        with open(relative_path, 'w') as f:
            f.write(test_content)
        self.temp_files.append(relative_path)
        
        file_content = FileSystem.read_file(relative_path)
        
        self.assertIsInstance(file_content, FileContent)
        self.assertEqual(file_content.as_binary, test_content.encode('utf-8'))

    def test_read_file_absolute_path(self):
        """
        GIVEN existing file at absolute path
        WHERE:
            - absolute_path = full system path to test file
        WHEN read_file is called
        THEN expect:
            - FileContent instance returned
            - File read from absolute location without errors
        """
        test_content = "Absolute path test content"
        temp_file = self._create_temp_file(test_content)
        absolute_path = os.path.abspath(temp_file)
        
        file_content = FileSystem.read_file(absolute_path)
        
        self.assertIsInstance(file_content, FileContent)
        self.assertEqual(file_content.as_binary, test_content.encode('utf-8'))



class TestFileSystemWriteFile(unittest.TestCase):
    """Test FileSystem.write_file static method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []
        self.temp_dirs = []

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    # Restore permissions before deletion
                    os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
                    os.unlink(temp_file)
            except OSError:
                pass
        
        # Clean up temporary directories
        for temp_dir in self.temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    # Restore permissions before deletion
                    os.chmod(temp_dir, 0o755)
                    os.rmdir(temp_dir)
            except OSError:
                pass

    def _create_temp_file_path(self, suffix=".txt"):
        """Helper method to create temporary file path without creating the file."""
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        os.unlink(temp_path)  # Remove the file, keep just the path
        self.temp_files.append(temp_path)
        return temp_path

    def test_write_file_new_file_binary_content_default_mode(self):
        """
        GIVEN path to new file that doesn't exist
        AND binary content and default mode
        WHERE:
            - new_file = path to file that doesn't exist
            - binary_content = b"binary test data"
            - default_mode = "wb"
        WHEN write_file is called
        THEN expect:
            - Return value == True
            - File created at specified path
            - File contains == binary_content
        """
        new_file = self._create_temp_file_path()
        binary_content = b"binary test data"
        
        # Ensure file doesn't exist
        self.assertFalse(os.path.exists(new_file))
        
        result = FileSystem.write_file(new_file, binary_content)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(new_file))
        
        # Verify content
        with open(new_file, 'rb') as f:
            written_content = f.read()
        self.assertEqual(written_content, binary_content)

    def test_write_file_new_file_string_content_binary_mode(self):
        """
        GIVEN path to new file
        AND string content and binary mode
        WHERE:
            - new_file = path to file that doesn't exist
            - string_content = "text content"
            - default_mode = "wb"
        WHEN write_file is called
        THEN expect:
            - String content encoded to bytes
            - File written without errors
            - Return value == True
        """
        new_file = self._create_temp_file_path()
        string_content = "text content"
        
        # Ensure file doesn't exist
        self.assertFalse(os.path.exists(new_file))
        
        result = FileSystem.write_file(new_file, string_content)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(new_file))
        
        # Verify content (string should be encoded to bytes)
        with open(new_file, 'rb') as f:
            written_content = f.read()
        self.assertEqual(written_content, string_content.encode('utf-8'))

    def test_write_file_existing_file_overwrite(self):
        """
        GIVEN path to existing file with existing content
        AND new content to write and default mode (overwrite)
        WHERE:
            - existing_file = path to file that already exists
            - binary_content = b"binary test data" (new content)
            - default_mode = "wb" (overwrite)
        WHEN write_file is called
        THEN expect:
            - Return value == True
            - Existing content replaced
            - File contains only binary_content
        """
        fd, existing_file = tempfile.mkstemp()
        self.temp_files.append(existing_file)
        
        # Write initial content
        os.write(fd, b"original content")
        os.close(fd)
        
        binary_content = b"new binary test data"
        
        result = FileSystem.write_file(existing_file, binary_content)
        
        self.assertTrue(result)
        
        # Verify content was overwritten
        with open(existing_file, 'rb') as f:
            written_content = f.read()
        self.assertEqual(written_content, binary_content)

    def test_write_file_with_text_mode(self):
        """
        GIVEN path to new file
        AND string content and text mode
        WHERE:
            - new_file = path to file that doesn't exist
            - string_content = "text content"
            - text_mode = "wt" or "w"
        WHEN write_file is called
        THEN expect:
            - Return value == True
            - Content written as text
            - Encoding handled per text mode specifications
        """
        new_file = self._create_temp_file_path()
        string_content = "text content with unicode: café 世界"
        
        result = FileSystem.write_file(new_file, string_content, mode="w")
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(new_file))
        
        # Verify content
        with open(new_file, 'r', encoding='utf-8') as f:
            written_content = f.read()
        self.assertEqual(written_content, string_content)

    def test_write_file_permission_denied(self):
        """
        GIVEN path in directory with restricted write permissions
        AND content to write
        WHERE:
            - permission_denied_path = path in directory with restricted write permissions
            - binary_content = b"binary test data"
        WHEN write_file is called
        THEN expect PermissionError to be raised
        """
        # Create directory with restricted permissions
        temp_dir = tempfile.mkdtemp()
        self.temp_dirs.append(temp_dir)
        
        os.chmod(temp_dir, 0o555)  # read and execute only, no write
        
        permission_denied_path = os.path.join(temp_dir, "test_file.txt")
        binary_content = b"binary test data"
        
        with self.assertRaises(PermissionError):
            FileSystem.write_file(permission_denied_path, binary_content)

    def test_write_file_directory_as_file_path(self):
        """
        GIVEN path that points to an existing directory
        AND content to write
        WHERE:
            - directory_as_file_path = path that points to existing directory
            - binary_content = b"binary test data"
        WHEN write_file is called
        THEN expect IsADirectoryError to be raised
        """
        directory_as_file_path = tempfile.mkdtemp()
        self.temp_dirs.append(directory_as_file_path)
        
        binary_content = b"binary test data"
        
        with self.assertRaises(IsADirectoryError):
            FileSystem.write_file(directory_as_file_path, binary_content)

    def test_write_file_parent_directory_missing(self):
        """
        GIVEN path where parent directory does not exist
        AND content to write
        WHERE:
            - parent_directory_missing = path where parent directory doesn't exist
            - binary_content = b"binary test data"
        WHEN write_file is called
        THEN expect:
            - FileNotFoundError to be raised
            - No file created
        """
        temp_base = tempfile.gettempdir()
        parent_directory_missing = os.path.join(temp_base, "nonexistent_dir_" + str(os.getpid()), "test_file.txt")
        binary_content = b"binary test data"
        
        # Ensure parent directory doesn't exist
        self.assertFalse(os.path.exists(os.path.dirname(parent_directory_missing)))
        
        with self.assertRaises(FileNotFoundError):
            FileSystem.write_file(parent_directory_missing, binary_content)
        
        # Verify no file was created
        self.assertFalse(os.path.exists(parent_directory_missing))

    def test_write_file_empty_content(self):
        """
        GIVEN path to new file
        AND empty content
        WHERE:
            - new_file = path to file that doesn't exist
            - empty_content = b"" or ""
        WHEN write_file is called
        THEN expect:
            - Return value == True
            - Empty file created
            - File size == 0 bytes
        """
        new_file = self._create_temp_file_path()
        empty_content = b""
        
        result = FileSystem.write_file(new_file, empty_content)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(new_file))
        
        # Verify file is empty
        stat_info = os.stat(new_file)
        self.assertEqual(stat_info.st_size, 0)
        
        with open(new_file, 'rb') as f:
            content = f.read()
        self.assertEqual(content, b"")

    def test_write_file_large_content(self):
        """
        GIVEN path to new file
        AND large content (>10MB)
        WHERE:
            - new_file = path to file that doesn't exist
            - large_content = content larger than 10MB
        WHEN write_file is called
        THEN expect:
            - Return value == True
            - All content written (no truncation)
            - File operation completes without errors
        """
        new_file = self._create_temp_file_path()
        large_content = b"x" * (10 * 1024 * 1024 + 1024)  # >10MB
        
        result = FileSystem.write_file(new_file, large_content)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(new_file))
        
        # Verify all content written
        stat_info = os.stat(new_file)
        self.assertEqual(stat_info.st_size, len(large_content))
        
        with open(new_file, 'rb') as f:
            written_content = f.read()
        self.assertEqual(written_content, large_content)

    def test_write_file_invalid_mode(self):
        """
        GIVEN path to file
        AND content to write and invalid mode parameter
        WHERE:
            - new_file = path to file
            - binary_content = b"binary test data"
            - invalid_mode = "invalid"
        WHEN write_file is called
        THEN expect ValueError to be raised
        """
        new_file = self._create_temp_file_path()
        binary_content = b"binary test data"
        
        with self.assertRaises(ValueError):
            FileSystem.write_file(new_file, binary_content, mode="invalid")

    def test_write_file_relative_path(self):
        """
        GIVEN relative file path
        AND content to write
        WHERE:
            - relative_path = "./new_file.txt"
            - binary_content = b"binary test data"
        WHEN write_file is called
        THEN expect:
            - Return value == True
            - File created at relative location
        """
        relative_path = "./test_write_file_" + str(os.getpid()) + ".txt"
        self.temp_files.append(relative_path)
        binary_content = b"binary test data"
        
        result = FileSystem.write_file(relative_path, binary_content)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(relative_path))
        
        # Verify content
        with open(relative_path, 'rb') as f:
            written_content = f.read()
        self.assertEqual(written_content, binary_content)

    def test_write_file_absolute_path(self):
        """
        GIVEN absolute file path
        AND content to write
        WHERE:
            - absolute_path = full system path for new file
            - binary_content = b"binary test data"
        WHEN write_file is called
        THEN expect:
            - Return value == True
            - File created at absolute location
        """
        absolute_path = os.path.abspath(self._create_temp_file_path())
        binary_content = b"binary test data"
        
        result = FileSystem.write_file(absolute_path, binary_content)
        
        self.assertTrue(result)
        self.assertTrue(os.path.exists(absolute_path))
        
        # Verify content
        with open(absolute_path, 'rb') as f:
            written_content = f.read()
        self.assertEqual(written_content, binary_content)


class TestFileSystemGetFileInfo(unittest.TestCase):
    """Test FileSystem.get_file_info static method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []
        self.temp_dirs = []

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    # Restore permissions before deletion
                    os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
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

    def _create_temp_file(self, content="test content", suffix=".txt", mode="w"):
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

    def test_get_file_info_existing_text_file(self):
        """
        GIVEN existing text file with known properties
        WHERE:
            - existing_text_file = temporary text file with known content
            - file has measurable size, modification time, permissions
        WHEN get_file_info is called with the file path
        THEN expect:
            - FileInfo instance returned
            - All attributes populated (path, size, modified_time, mime_type, extension, is_readable, is_writable)
            - Values match actual file properties within 1-second precision for timestamps
        """
        test_content = "Hello, World! Test file content."
        temp_file = self._create_temp_file(test_content, suffix=".txt")
        
        file_info = FileSystem.get_file_info(temp_file)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.path, Path(temp_file))
        self.assertEqual(file_info.size, len(test_content.encode('utf-8')))
        
        # Check timestamp within 1 second
        now = datetime.now()
        time_diff = abs((now - file_info.modified_time).total_seconds())
        self.assertLessEqual(time_diff, 1)
        
        self.assertTrue(file_info.mime_type.startswith("text/"))
        self.assertEqual(file_info.extension, "txt")
        self.assertTrue(file_info.is_readable)
        self.assertTrue(file_info.is_writable)

    def test_get_file_info_existing_binary_file(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary binary file
        WHEN get_file_info is called
        THEN expect:
            - FileInfo instance returned
            - MIME type identified as binary type
            - All other attributes populated per file properties
        """
        binary_content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        temp_file = self._create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileSystem.get_file_info(temp_file)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.mime_type, "image/png")
        self.assertEqual(file_info.path, Path(temp_file))
        self.assertEqual(file_info.size, len(binary_content))
        self.assertEqual(file_info.extension, "png")

    def test_get_file_info_nonexistent_file(self):
        """
        GIVEN path to file that does not exist
        WHERE:
            - nonexistent_file = "/path/that/does/not/exist.txt"
        WHEN get_file_info is called
        THEN expect FileNotFoundError to be raised
        """
        nonexistent_file = "/path/that/does/not/exist.txt"
        
        with self.assertRaises(FileNotFoundError):
            FileSystem.get_file_info(nonexistent_file)

    def test_get_file_info_directory_path(self):
        """
        GIVEN path pointing to a directory instead of a file
        WHERE:
            - directory_path = path to existing directory
        WHEN get_file_info is called
        THEN expect ValueError to be raised (pydantic validation)
        """
        directory_path = tempfile.mkdtemp()
        self.temp_dirs.append(directory_path)
        
        with self.assertRaises(ValueError):
            FileSystem.get_file_info(directory_path)

    def test_get_file_info_empty_file(self):
        """
        GIVEN existing empty file (0 bytes)
        WHERE:
            - empty_file = file with 0 bytes
        WHEN get_file_info is called
        THEN expect:
            - FileInfo instance returned
            - size attribute == 0
            - Other attributes populated per normal rules
        """
        temp_file = self._create_temp_file("")
        
        file_info = FileSystem.get_file_info(temp_file)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.size, 0)
        self.assertIsInstance(file_info.modified_time, datetime)
        self.assertIsNotNone(file_info.mime_type)

    def test_get_file_info_file_with_no_extension(self):
        """
        GIVEN existing file without extension
        WHERE:
            - no_extension_file = "README" (file without extension)
        WHEN get_file_info is called
        THEN expect:
            - FileInfo instance returned
            - extension attribute == ""
            - MIME type determined by content analysis
        """
        # Create file without extension
        fd, temp_path = tempfile.mkstemp(suffix="")
        os.close(fd)
        os.unlink(temp_path)
        
        no_extension_path = temp_path + "_README"
        with open(no_extension_path, 'w') as f:
            f.write("# README\nThis is a readme file.")
        self.temp_files.append(no_extension_path)
        
        file_info = FileSystem.get_file_info(no_extension_path)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.extension, "")
        self.assertEqual(file_info.mime_type, "text/plain")

    def test_get_file_info_permission_restrictions(self):
        """
        GIVEN file with restricted permissions
        WHERE:
            - restricted_permissions_file = file with specific permission restrictions
        WHEN get_file_info is called
        THEN expect:
            - FileInfo instance returned
            - is_readable and is_writable attributes reflect actual file permissions
            - No permission errors raised during info gathering
        """
        temp_file = self._create_temp_file("test content")
        
        # Set specific permissions: read-only for owner, no access for others
        os.chmod(temp_file, 0o400)
        
        file_info = FileSystem.get_file_info(temp_file)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertTrue(file_info.is_readable)  # Owner can read
        self.assertFalse(file_info.is_writable)  # Owner cannot write
        
        # Test no permissions
        os.chmod(temp_file, 0o000)
        
        file_info = FileSystem.get_file_info(temp_file)
        self.assertFalse(file_info.is_readable)
        self.assertFalse(file_info.is_writable)

    def test_get_file_info_relative_path(self):
        """
        GIVEN existing file at relative path
        WHERE:
            - relative_path = "./test_file.txt"
            - file exists at relative location
        WHEN get_file_info is called
        THEN expect:
            - FileInfo instance returned
            - path attribute contains provided relative path
            - File info gathered without errors
        """
        temp_file = self._create_temp_file("test content")
        relative_path = "./" + os.path.basename(temp_file)
        
        # Create file at relative path
        with open(relative_path, 'w') as f:
            f.write("test content")
        self.temp_files.append(relative_path)
        
        file_info = FileSystem.get_file_info(relative_path)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertIn(relative_path.strip('.'), str(file_info.path))

    def test_get_file_info_absolute_path(self):
        """
        GIVEN existing file at absolute path
        WHERE:
            - absolute_path = full system path to test file
        WHEN get_file_info is called
        THEN expect:
            - FileInfo instance returned
            - path attribute contains provided absolute path
        """
        temp_file = self._create_temp_file("test content")
        absolute_path = os.path.abspath(temp_file)
        
        file_info = FileSystem.get_file_info(absolute_path)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.path, Path(absolute_path))

    def test_get_file_info_symlink_file(self):
        """
        GIVEN symbolic link pointing to an existing file
        WHERE:
            - symlink_file = symbolic link to existing file
        WHEN get_file_info is called on the symlink path
        THEN expect:
            - FileInfo instance returned
            - Information reflects target file
            - No errors with symlink handling
        """
        # Create target file
        target_file = self._create_temp_file("symlink target content")
        
        # Create symlink
        symlink_path = target_file + "_symlink"
        os.symlink(target_file, symlink_path)
        self.temp_files.append(symlink_path)
        
        file_info = FileSystem.get_file_info(symlink_path)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.path, Path(symlink_path))
        # Size should match target file
        self.assertEqual(file_info.size, len("symlink target content".encode('utf-8')))

    def test_get_file_info_recently_modified_file(self):
        """
        GIVEN file that was recently modified
        WHERE:
            - recently_modified_file = file modified within last minute
        WHEN get_file_info is called
        THEN expect:
            - FileInfo instance returned
            - modified_time attribute reflects recent modification time
            - Timestamp within 1-second precision of actual modification time
        """
        temp_file = self._create_temp_file("initial content")
        
        # Modify the file
        modification_time = datetime.now()
        with open(temp_file, 'a') as f:
            f.write(" additional content")
        
        file_info = FileSystem.get_file_info(temp_file)
        
        self.assertIsInstance(file_info, FileInfo)
        
        # Check that modification time is recent (within 1 second)
        time_diff = abs((modification_time - file_info.modified_time).total_seconds())
        self.assertLessEqual(time_diff, 1)


class TestFileSystemListFiles(unittest.TestCase):
    """Test FileSystem.list_files static method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []
        self.temp_dirs = []

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    # Restore permissions before deletion
                    os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
                    os.unlink(temp_file)
            except OSError:
                pass
        
        # Clean up temporary directories (in reverse order for nested dirs)
        for temp_dir in reversed(self.temp_dirs):
            try:
                if os.path.exists(temp_dir):
                    # Restore permissions before deletion
                    os.chmod(temp_dir, 0o755)
                    os.rmdir(temp_dir)
            except OSError:
                pass

    def _create_test_directory_with_files(self):
        """Helper method to create a test directory with various file types."""
        test_dir = tempfile.mkdtemp()
        self.temp_dirs.append(test_dir)
        
        # Create various files
        files_to_create = [
            ("test.txt", "text content"),
            ("script.py", "# Python script"),
            ("image.jpg", "fake jpg content"),
            ("README", "readme content"),  # No extension
            ("Makefile", "makefile content"),  # No extension
            ("Test.TXT", "uppercase extension"),
            ("file.Txt", "mixed case extension")
        ]
        
        created_files = []
        for filename, content in files_to_create:
            file_path = os.path.join(test_dir, filename)
            with open(file_path, 'w') as f:
                f.write(content)
            self.temp_files.append(file_path)
            created_files.append(file_path)
        
        # Create a subdirectory (should be excluded from file listings)
        subdir = os.path.join(test_dir, "subdir")
        os.makedirs(subdir)
        self.temp_dirs.append(subdir)
        
        return test_dir, created_files

    def test_list_files_existing_directory_default_pattern_returns_list(self):
        """
        GIVEN existing directory with mixed file types
        AND default pattern
        WHERE:
            - existing_directory = directory with mixed file types
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - Return type == list
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        self.assertIsInstance(result, list)

    def test_list_files_existing_directory_default_pattern_returns_string_paths(self):
        """
        GIVEN existing directory with mixed file types
        AND default pattern
        WHERE:
            - existing_directory = directory with mixed file types
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - All items in list are strings
        """
        test_dir, created_files = self._create_test_directory_with_files()

        result = FileSystem.list_files(test_dir)

        for item in result:
            self.assertIsInstance(item, str)

    def test_list_files_existing_directory_default_pattern_correct_count(self):
        """
        GIVEN existing directory with mixed file types
        AND default pattern
        WHERE:
            - existing_directory = directory with mixed file types
            - default_pattern = "*.*"
            - mixed_file_types = files with various extensions (.txt, .py, .jpg, etc.)
        WHEN list_files is called
        THEN expect:
            - Count matches files with extensions (excludes files without extensions)
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        # Should include files with extensions
        expected_files = [f for f in created_files if '.' in os.path.basename(f)]
        self.assertEqual(len(result), len(expected_files))

    def test_list_files_existing_directory_default_pattern_includes_txt_file(self):
        """
        GIVEN existing directory with mixed file types including test.txt
        AND default pattern
        WHERE:
            - existing_directory = directory with test.txt file
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - test.txt included in results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        result_basenames = [os.path.basename(f) for f in result]
        self.assertIn("test.txt", result_basenames)

    def test_list_files_existing_directory_default_pattern_includes_py_file(self):
        """
        GIVEN existing directory with mixed file types including script.py
        AND default pattern
        WHERE:
            - existing_directory = directory with script.py file
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - script.py included in results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        result_basenames = [os.path.basename(f) for f in result]
        self.assertIn("script.py", result_basenames)

    def test_list_files_existing_directory_default_pattern_includes_jpg_file(self):
        """
        GIVEN existing directory with mixed file types including image.jpg
        AND default pattern
        WHERE:
            - existing_directory = directory with image.jpg file
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - image.jpg included in results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        result_basenames = [os.path.basename(f) for f in result]
        self.assertIn("image.jpg", result_basenames)

    def test_list_files_existing_directory_default_pattern_includes_uppercase_txt(self):
        """
        GIVEN existing directory with mixed file types including Test.TXT
        AND default pattern
        WHERE:
            - existing_directory = directory with Test.TXT file
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - Test.TXT included in results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        result_basenames = [os.path.basename(f) for f in result]
        self.assertIn("Test.TXT", result_basenames)

    def test_list_files_existing_directory_default_pattern_includes_mixed_case_txt(self):
        """
        GIVEN existing directory with mixed file types including file.Txt
        AND default pattern
        WHERE:
            - existing_directory = directory with file.Txt file
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - file.Txt included in results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        result_basenames = [os.path.basename(f) for f in result]
        self.assertIn("file.Txt", result_basenames)

    def test_list_files_existing_directory_default_pattern_excludes_readme(self):
        """
        GIVEN existing directory with mixed file types including README (no extension)
        AND default pattern
        WHERE:
            - existing_directory = directory with README file (no extension)
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - README excluded from results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        result_basenames = [os.path.basename(f) for f in result]
        self.assertNotIn("README", result_basenames)

    def test_list_files_existing_directory_default_pattern_excludes_makefile(self):
        """
        GIVEN existing directory with mixed file types including Makefile (no extension)
        AND default pattern
        WHERE:
            - existing_directory = directory with Makefile file (no extension)
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - Makefile excluded from results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir)
        
        result_basenames = [os.path.basename(f) for f in result]
        self.assertNotIn("Makefile", result_basenames)

    def test_list_files_existing_directory_wildcard_pattern_includes_files_with_extension(self):
        """
        GIVEN existing directory with various file types
        AND pattern for all files
        WHERE:
            - existing_directory = directory with various file types
            - wildcard_pattern = "*"
        WHEN list_files is called
        THEN expect:
            - List includes all files regardless of extension
        """
        test_dir, created_files = self._create_test_directory_with_files()

        result = FileSystem.list_files(test_dir, pattern="*")

        expected_txt_files = ["test.txt", "script.py"]
        for file in expected_txt_files:
            self.assertIn(file, [os.path.basename(f) for f in result])

    def test_list_files_existing_directory_wildcard_pattern_includes_files_without_extensions(self):
        """
        GIVEN existing directory with files without extensions
        AND pattern for all files
        WHERE:
            - existing_directory = directory with files like "README", "Makefile"
            - wildcard_pattern = "*"
        WHEN list_files is called
        THEN expect:
            - Files without extensions included in results
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir, pattern="*")
        
        result_basenames = [os.path.basename(f) for f in result]
        
        # Files without extensions should be included
        for file_without_ext in ["README", "Makefile"]:
            self.assertIn(file_without_ext, result_basenames)


    def test_list_files_specific_extension_pattern_includes_matching_files(self):
        """
        GIVEN directory containing files with various extensions
        AND specific pattern
        WHERE:
            - existing_directory = directory with files: test.txt, Test.TXT, script.py, image.jpg
            - specific_extension = "*.txt"
        WHEN list_files is called
        THEN expect:
            - Files with .txt extension included: [test.txt, Test.TXT, file.Txt]
            - Case-insensitive matching (both .txt and .TXT match)
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir, pattern="*.txt")
        
        self.assertIsInstance(result, list)
        
        result_basenames = [os.path.basename(f) for f in result]
        
        # Should include .txt files (case-insensitive)
        expected_txt_files = ["test.txt", "Test.TXT", "file.Txt"]
        for txt_file in expected_txt_files:
            self.assertIn(txt_file, result_basenames)

    def test_list_files_specific_extension_pattern_excludes_non_matching_files(self):
        """
        GIVEN directory containing files with various extensions
        AND specific pattern
        WHERE:
            - existing_directory = directory with files: test.txt, Test.TXT, script.py, image.jpg
            - specific_extension = "*.txt"
        WHEN list_files is called
        THEN expect:
            - Other file types (.py, .jpg) excluded
            - Files without extensions excluded
        """
        test_dir, created_files = self._create_test_directory_with_files()
        
        result = FileSystem.list_files(test_dir, pattern="*.txt")
        
        result_basenames = [os.path.basename(f) for f in result]
        
        # Should exclude non-.txt files
        excluded_files = ["script.py", "image.jpg", "README", "Makefile"]
        for excluded_file in excluded_files:
            self.assertNotIn(excluded_file, result_basenames)

    def test_list_files_empty_directory(self):
        """
        GIVEN existing but empty directory
        AND any pattern
        WHERE:
            - empty_directory = directory with no files
            - default_pattern = "*.*"
        WHEN list_files is called
        THEN expect:
            - Empty list returned (== [])
            - No errors raised
        """
        empty_directory = tempfile.mkdtemp()
        self.temp_dirs.append(empty_directory)
        
        result = FileSystem.list_files(empty_directory)
        
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    def test_list_files_nonexistent_directory(self):
        """
        GIVEN path to directory that does not exist
        WHERE:
            - nonexistent_directory = "/path/that/does/not/exist"
        WHEN list_files is called
        THEN expect FileNotFoundError to be raised
        """
        nonexistent_directory = "/path/that/does/not/exist"
        
        with self.assertRaises(FileNotFoundError):
            FileSystem.list_files(nonexistent_directory)

    def test_list_files_file_path_instead_of_directory(self):
        """
        GIVEN path pointing to a file instead of directory
        WHERE:
            - file_path_instead = path to file instead of directory
        WHEN list_files is called
        THEN expect NotADirectoryError to be raised
        """
        # Create a file
        fd, file_path_instead = tempfile.mkstemp()
        os.close(fd)
        self.temp_files.append(file_path_instead)
        
        with open(file_path_instead, 'w') as f:
            f.write("test content")
        
        with self.assertRaises(NotADirectoryError):
            FileSystem.list_files(file_path_instead)

    def test_list_files_permission_denied_directory(self):
        """
        GIVEN directory that exists but cannot be read due to permissions
        WHERE:
            - permission_denied_directory = directory with restricted read permissions
        WHEN list_files is called
        THEN expect PermissionError to be raised
        """
        permission_denied_directory = tempfile.mkdtemp()
        self.temp_dirs.append(permission_denied_directory)
        
        # Create some files first
        test_file = os.path.join(permission_denied_directory, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        self.temp_files.append(test_file)
        
        # Remove read permissions
        os.chmod(permission_denied_directory, 0o000)
        
        with self.assertRaises(PermissionError):
            FileSystem.list_files(permission_denied_directory)

    def test_list_files_complex_pattern_matching(self):
        """
        GIVEN directory with various file names
        AND complex pattern
        WHERE:
            - existing_directory = directory with various file names
            - complex_pattern = "test_*.py"
            - mixed_file_types = files with various extensions and naming patterns
        WHEN list_files is called
        THEN expect:
            - Only files matching the specific pattern returned
            - Pattern matching follows glob rules
        """
        test_dir = tempfile.mkdtemp()
        self.temp_dirs.append(test_dir)
        
        # Create files with various patterns
        files_to_create = [
            "test_module.py",  # Should match
            "test_helper.py",  # Should match
            "test.py",         # Should NOT match (no underscore)
            "my_test_file.py", # Should NOT match (doesn't start with test_)
            "test_script.txt", # Should NOT match (wrong extension)
            "test_data.py"     # Should match
        ]
        
        for filename in files_to_create:
            file_path = os.path.join(test_dir, filename)
            with open(file_path, 'w') as f:
                f.write("content")
            self.temp_files.append(file_path)
        
        result = FileSystem.list_files(test_dir, pattern="test_*.py")
        
        result_basenames = [os.path.basename(f) for f in result]
        
        # Should match
        self.assertIn("test_module.py", result_basenames)
        self.assertIn("test_helper.py", result_basenames)
        self.assertIn("test_data.py", result_basenames)
        
        # Should not match
        self.assertNotIn("test.py", result_basenames)
        self.assertNotIn("my_test_file.py", result_basenames)
        self.assertNotIn("test_script.txt", result_basenames)

    def test_list_files_relative_directory_path(self):
        """
        GIVEN relative path to existing directory
        WHERE:
            - relative_directory = "./test_dir"
            - directory exists at relative location
        WHEN list_files is called
        THEN expect:
            - Files listed from relative directory without errors
            - Returned paths follow consistent format
        """
        # Create directory in current directory
        relative_directory = "./test_list_files_" + str(os.getpid())
        os.makedirs(relative_directory)
        self.temp_dirs.append(relative_directory)
        
        # Create test file
        test_file = os.path.join(relative_directory, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        self.temp_files.append(test_file)
        
        result = FileSystem.list_files(relative_directory)
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        result_basenames = [os.path.basename(f) for f in result]
        self.assertIn("test.txt", result_basenames)

    def test_list_files_absolute_directory_path(self):
        """
        GIVEN absolute path to existing directory
        WHERE:
            - absolute_directory = full system path to directory
        WHEN list_files is called
        THEN expect:
            - Files listed from absolute directory without errors
            - Returned paths follow consistent format
        """
        test_dir = tempfile.mkdtemp()
        absolute_directory = os.path.abspath(test_dir)
        self.temp_dirs.append(absolute_directory)
        
        # Create test file
        test_file = os.path.join(absolute_directory, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        self.temp_files.append(test_file)
        
        result = FileSystem.list_files(absolute_directory)
        
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        result_basenames = [os.path.basename(f) for f in result]
        self.assertIn("test.txt", result_basenames)

    def test_list_files_hidden_files_handling(self):
        """
        GIVEN directory containing hidden files
        AND appropriate pattern to match hidden files
        WHERE:
            - existing_directory = directory with mixed file types
            - hidden_files_pattern = ".*"
            - hidden_files = files starting with "."
        WHEN list_files is called
        THEN expect:
            - hidden_files included or excluded based on pattern
            - Behavior consistent with pattern matching rules
        """
        test_dir = tempfile.mkdtemp()
        self.temp_dirs.append(test_dir)
        
        # Create regular and hidden files
        files_to_create = [
            "regular.txt",
            ".hidden_file",
            ".hidden_config",
            "another.py"
        ]
        
        for filename in files_to_create:
            file_path = os.path.join(test_dir, filename)
            with open(file_path, 'w') as f:
                f.write("content")
            self.temp_files.append(file_path)
        
        # Test pattern for hidden files
        result_hidden = FileSystem.list_files(test_dir, pattern=".*")
        result_hidden_basenames = [os.path.basename(f) for f in result_hidden]
        
        # Should include hidden files
        self.assertIn(".hidden_file", result_hidden_basenames)
        self.assertIn(".hidden_config", result_hidden_basenames)
        
        # Test default pattern (should exclude hidden files)
        result_regular = FileSystem.list_files(test_dir, pattern="*.*")
        result_regular_basenames = [os.path.basename(f) for f in result_regular]
        
        # Should include regular files
        self.assertIn("regular.txt", result_regular_basenames)
        self.assertIn("another.py", result_regular_basenames)
        
        # Should exclude hidden files with default pattern
        self.assertNotIn(".hidden_file", result_regular_basenames)
        self.assertNotIn(".hidden_config", result_regular_basenames)

    def test_list_files_case_sensitive_pattern(self):
        """
        GIVEN directory with files having different case extensions
        AND case-specific pattern
        WHERE:
            - existing_directory = directory with files: file.TXT, file.txt, file.Txt
            - case_specific_pattern = "*.TXT" vs "*.txt"
        WHEN list_files is called with each pattern
        THEN expect:
            - Case-insensitive matching behavior
            - "*.TXT" matches all three files (file.TXT, file.txt, file.Txt)
            - "*.txt" matches all three files (file.TXT, file.txt, file.Txt)
            - Consistent behavior across different case patterns
        """
        test_dir = tempfile.mkdtemp()
        self.temp_dirs.append(test_dir)
        
        # Create files with different case extensions
        files_to_create = [
            "file.TXT",
            "file.txt", 
            "file.Txt",
            "other.py"  # Should not match txt patterns
        ]
        
        for filename in files_to_create:
            file_path = os.path.join(test_dir, filename)
            with open(file_path, 'w') as f:
                f.write("content")
            self.temp_files.append(file_path)
        
        # Test uppercase pattern
        result_upper = FileSystem.list_files(test_dir, pattern="*.TXT")
        result_upper_basenames = [os.path.basename(f) for f in result_upper]
        
        # Test lowercase pattern
        result_lower = FileSystem.list_files(test_dir, pattern="*.txt")
        result_lower_basenames = [os.path.basename(f) for f in result_lower]
        
        # Both patterns should match all txt files (case-insensitive)
        expected_txt_files = ["file.TXT", "file.txt", "file.Txt"]
        
        for txt_file in expected_txt_files:
            self.assertIn(txt_file, result_upper_basenames)
            self.assertIn(txt_file, result_lower_basenames)
        
        # Should not match non-txt files
        self.assertNotIn("other.py", result_upper_basenames)
        self.assertNotIn("other.py", result_lower_basenames)
        
        # Results should be identical
        self.assertEqual(set(result_upper_basenames), set(result_lower_basenames))

if __name__ == '__main__':
    unittest.main()