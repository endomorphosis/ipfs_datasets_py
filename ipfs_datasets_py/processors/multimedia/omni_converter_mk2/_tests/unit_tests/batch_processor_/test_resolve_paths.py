import unittest
import tempfile
import os
import glob
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
from types_ import Logger, Generator


from batch_processor._resolve_paths import resolve_paths, _resolve_path


class TestResolvePathsFunction(unittest.TestCase):
    """Test suite for the resolve_paths function and _resolve_path generator."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = MagicMock(spec=Logger)
        
        # Create a temporary directory for actual file tests
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_test_dir)

    def _cleanup_test_dir(self):
        """Clean up the temporary test directory."""
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def _create_test_files(self, file_structure):
        """
        Create test files and directories based on structure dict.
        
        Args:
            file_structure: Dict with paths as keys and content as values.
                           Use None for directories.
        """
        for path, content in file_structure.items():
            full_path = os.path.join(self.test_dir, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            if content is None:  # Directory
                os.makedirs(full_path, exist_ok=True)
            else:  # File
                with open(full_path, 'w') as f:
                    f.write(content)

    def test_resolve_paths_with_string_input_single_file(self):
        """
        GIVEN a single file path as string that exists
        WHEN resolve_paths is called
        THEN expect:
            - Single file path returned in list
            - Path is absolute
            - No warnings logged
        """
        # Arrange
        test_file = os.path.join(self.test_dir, 'test_file.txt')
        with open(test_file, 'w') as f:
            f.write('test content')
        
        # Act
        result = resolve_paths(test_file, self.mock_logger)
        
        # Assert
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], os.path.abspath(test_file))
        self.assertTrue(os.path.isabs(result[0]))
        self.mock_logger.warning.assert_not_called()

    def test_resolve_paths_with_string_input_nonexistent_file(self):
        """
        GIVEN a single file path as string that does not exist
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - Warning logged about file not found
        """
        # Arrange
        nonexistent_file = os.path.join(self.test_dir, 'nonexistent.txt')
        
        # Act
        result = resolve_paths(nonexistent_file, self.mock_logger)
        
        # Assert
        self.assertEqual(len(result), 0)
        self.mock_logger.warning.assert_called_once()
        warning_call = self.mock_logger.warning.call_args[0][0]
        self.assertIn('Path not found', warning_call)
        self.assertIn(nonexistent_file, warning_call)

    def test_resolve_paths_with_list_input_mixed_files(self):
        """
        GIVEN a list of file paths with some existing and some non-existing
        WHEN resolve_paths is called
        THEN expect:
            - Only existing files returned
            - Warnings logged for non-existing files
            - Order preserved for existing files
        """
        # Arrange
        existing_file1 = os.path.join(self.test_dir, 'file1.txt')
        existing_file2 = os.path.join(self.test_dir, 'file2.txt')
        nonexistent_file = os.path.join(self.test_dir, 'nonexistent.txt')
        
        with open(existing_file1, 'w') as f:
            f.write('content1')
        with open(existing_file2, 'w') as f:
            f.write('content2')
        
        file_paths = [existing_file1, nonexistent_file, existing_file2]
        
        # Act
        result = resolve_paths(file_paths, self.mock_logger)
        
        # Assert
        self.assertEqual(len(result), 2)
        self.assertIn(os.path.abspath(existing_file1), result)
        self.assertIn(os.path.abspath(existing_file2), result)
        self.mock_logger.warning.assert_called_once()

    def test_resolve_paths_with_directory_input(self):
        """
        GIVEN a directory path as string
        WHEN resolve_paths is called
        THEN expect:
            - All files in directory and subdirectories returned
            - No directories in result
            - All paths are absolute
        """
        # Arrange
        file_structure = {
            'file1.txt': 'content1',
            'subdir/file2.txt': 'content2',
            'subdir/nested/file3.txt': 'content3',
            'empty_dir': None  # Directory
        }
        self._create_test_files(file_structure)
        
        # Act
        result = resolve_paths(self.test_dir, self.mock_logger)
        
        # Assert
        self.assertEqual(len(result), 3)  # Only files, not directories
        
        expected_files = [
            os.path.abspath(os.path.join(self.test_dir, 'file1.txt')),
            os.path.abspath(os.path.join(self.test_dir, 'subdir', 'file2.txt')),
            os.path.abspath(os.path.join(self.test_dir, 'subdir', 'nested', 'file3.txt'))
        ]
        
        for expected_file in expected_files:
            self.assertIn(expected_file, result)
        
        # Verify all paths are absolute
        for path in result:
            self.assertTrue(os.path.isabs(path))

    @patch('glob.glob')
    def test_resolve_paths_with_glob_pattern_matches(self, mock_glob):
        """
        GIVEN a glob pattern that matches multiple files
        WHEN resolve_paths is called
        THEN expect:
            - All matching files returned
            - Paths are absolute
            - glob.glob called with correct arguments
        """
        # Arrange
        pattern = os.path.join(self.test_dir, '*.txt')
        mock_matches = [
            os.path.join(self.test_dir, 'file1.txt'),
            os.path.join(self.test_dir, 'file2.txt')
        ]
        mock_glob.return_value = mock_matches
        
        # Create the actual files so isfile check passes
        for match in mock_matches:
            with open(match, 'w') as f:
                f.write('content')
        
        # Act
        result = resolve_paths(pattern, self.mock_logger)
        
        # Assert
        mock_glob.assert_called_once_with(pattern, recursive=True)
        self.assertEqual(len(result), 2)
        for match in mock_matches:
            self.assertIn(os.path.abspath(match), result)

    @patch('glob.glob')
    def test_resolve_paths_with_glob_pattern_no_matches(self, mock_glob):
        """
        GIVEN a glob pattern that matches no files
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - No warnings logged (empty glob is valid)
        """
        # Arrange
        pattern = os.path.join(self.test_dir, '*.nonexistent')
        mock_glob.return_value = []
        
        # Act
        result = resolve_paths(pattern, self.mock_logger)
        
        # Assert
        mock_glob.assert_called_once_with(pattern, recursive=True)
        self.assertEqual(len(result), 0)
        self.mock_logger.warning.assert_not_called()

    @patch('os.path.islink')
    @patch('os.path.realpath')
    def test_resolve_paths_with_symlink_valid_target(self, mock_realpath, mock_islink):
        """
        GIVEN a symlink that points to an existing file
        WHEN resolve_paths is called
        THEN expect:
            - Resolved target path returned
            - Path is absolute
            - realpath called for symlink resolution
        """
        # Arrange
        target_file = os.path.join(self.test_dir, 'target.txt')
        symlink_file = os.path.join(self.test_dir, 'symlink.txt')
        
        with open(target_file, 'w') as f:
            f.write('target content')
        
        mock_islink.return_value = True
        mock_realpath.return_value = target_file
        
        # Mock os.path.exists to return True for the resolved path
        with patch('os.path.exists', return_value=True):
            # Act
            result = resolve_paths(symlink_file, self.mock_logger)
        
        # Assert
        mock_islink.assert_called_once_with(symlink_file)
        mock_realpath.assert_called_once_with(symlink_file)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], os.path.abspath(target_file))

    @patch('os.path.islink')
    @patch('os.path.realpath')
    @patch('os.path.exists')
    def test_resolve_paths_with_symlink_broken_target(self, mock_exists, mock_realpath, mock_islink):
        """
        GIVEN a symlink that points to a non-existing file
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - Warning logged about broken symlink
        """
        # Arrange
        symlink_file = os.path.join(self.test_dir, 'broken_symlink.txt')
        broken_target = os.path.join(self.test_dir, 'nonexistent_target.txt')
        
        mock_islink.return_value = True
        mock_realpath.return_value = broken_target
        mock_exists.return_value = False
        
        # Act
        result = resolve_paths(symlink_file, self.mock_logger)
        
        # Assert
        self.assertEqual(len(result), 0)
        self.mock_logger.warning.assert_called_once()

    def test_resolve_paths_with_invalid_input_type(self):
        """
        GIVEN an invalid input type (not string or list)
        WHEN resolve_paths is called
        THEN expect:
            - ValueError raised with descriptive message
        """
        # Arrange
        invalid_input = 12345
        
        # Act & Assert
        with self.assertRaises(ValueError) as context:
            resolve_paths(invalid_input, self.mock_logger)
        
        self.assertIn("Invalid input type", str(context.exception))
        self.assertIn("Must be a string or list of strings", str(context.exception))

    def test_resolve_paths_with_empty_list(self):
        """
        GIVEN an empty list
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - No warnings logged
        """
        # Act
        result = resolve_paths([], self.mock_logger)
        
        # Assert
        self.assertEqual(len(result), 0)
        self.mock_logger.warning.assert_not_called()

    def test_resolve_paths_preserves_order(self):
        """
        GIVEN a list of existing files in specific order
        WHEN resolve_paths is called
        THEN expect:
            - Results maintain the same order as input
        """
        # Arrange
        files = [
            os.path.join(self.test_dir, 'zebra.txt'),
            os.path.join(self.test_dir, 'alpha.txt'),
            os.path.join(self.test_dir, 'beta.txt')
        ]
        
        for file_path in files:
            with open(file_path, 'w') as f:
                f.write('content')
        
        # Act
        result = resolve_paths(files, self.mock_logger)
        
        # Assert
        self.assertEqual(len(result), 3)
        for i, file_path in enumerate(files):
            self.assertEqual(result[i], os.path.abspath(file_path))

    def test_resolve_paths_handles_relative_paths(self):
        """
        GIVEN relative file paths
        WHEN resolve_paths is called
        THEN expect:
            - Paths converted to absolute paths
            - Files resolved correctly relative to current directory
        """
        # Arrange - Create a file in current directory context
        current_dir = os.getcwd()
        try:
            os.chdir(self.test_dir)
            
            # Create files with relative paths
            with open('relative_file.txt', 'w') as f:
                f.write('content')
            
            relative_path = './relative_file.txt'
            
            # Act
            result = resolve_paths(relative_path, self.mock_logger)
            
            # Assert
            self.assertEqual(len(result), 1)
            self.assertTrue(os.path.isabs(result[0]))
            self.assertTrue(result[0].endswith('relative_file.txt'))
            
        finally:
            os.chdir(current_dir)

    @patch('glob.glob')
    def test_resolve_paths_with_recursive_glob_pattern(self, mock_glob):
        """
        GIVEN a recursive glob pattern (**)
        WHEN resolve_paths is called
        THEN expect:
            - glob.glob called with recursive=True
            - All matching files from subdirectories included
        """
        # Arrange
        pattern = os.path.join(self.test_dir, '**', '*.txt')
        mock_matches = [
            os.path.join(self.test_dir, 'file1.txt'),
            os.path.join(self.test_dir, 'subdir', 'file2.txt'),
            os.path.join(self.test_dir, 'subdir', 'nested', 'file3.txt')
        ]
        mock_glob.return_value = mock_matches
        
        # Create the actual files
        for match in mock_matches:
            os.makedirs(os.path.dirname(match), exist_ok=True)
            with open(match, 'w') as f:
                f.write('content')
        
        # Act
        result = resolve_paths(pattern, self.mock_logger)
        
        # Assert
        mock_glob.assert_called_once_with(pattern, recursive=True)
        self.assertEqual(len(result), 3)


class TestResolvePathGenerator(unittest.TestCase):
    """Test suite specifically for the _resolve_path generator function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = MagicMock(spec=Logger)
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_test_dir)

    def _cleanup_test_dir(self):
        """Clean up the temporary test directory."""
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_resolve_path_generator_yields_correct_type(self):
        """
        GIVEN a valid file path
        WHEN _resolve_path generator is called
        THEN expect:
            - Generator object returned
            - Yields strings only
        """
        # Arrange
        test_file = os.path.join(self.test_dir, 'test.txt')
        with open(test_file, 'w') as f:
            f.write('content')
        
        # Act
        generator = _resolve_path(test_file, self.mock_logger)
        
        # Assert
        self.assertIsInstance(generator, Generator)
        
        results = list(generator)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], str)

    def test_resolve_path_generator_memory_efficient(self):
        """
        GIVEN a directory with many files
        WHEN _resolve_path generator is used
        THEN expect:
            - Generator doesn't load all files into memory at once
            - Can be consumed iteratively
        """
        # Arrange - Create many files
        num_files = 100
        for i in range(num_files):
            with open(os.path.join(self.test_dir, f'file_{i:03d}.txt'), 'w') as f:
                f.write(f'content {i}')
        
        # Act
        generator = _resolve_path(self.test_dir, self.mock_logger)
        
        # Assert - Generator should not immediately consume all files
        self.assertIsInstance(generator, Generator)
        
        # Consume first few items
        first_items = []
        for i, item in enumerate(generator):
            first_items.append(item)
            if i >= 4:  # Take first 5 items
                break
        
        self.assertEqual(len(first_items), 5)
        
        # Continue consuming the rest
        remaining_items = list(generator)
        total_items = len(first_items) + len(remaining_items)
        self.assertEqual(total_items, num_files)


if __name__ == '__main__':
    unittest.main()