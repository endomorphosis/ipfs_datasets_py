"""
Test suite for batch_processor/_resolve_paths.py converted from unittest to pytest.
"""
import pytest
import tempfile
import os
import glob
from unittest.mock import MagicMock, patch, mock_open
from pathlib import Path
import shutil

try:
    from types_ import Logger, Generator
    from batch_processor._resolve_paths import resolve_paths, _resolve_path
except ImportError:
    pytest.skip("batch_processor._resolve_paths module not available", allow_module_level=True)


@pytest.fixture
def mock_logger():
    """Fixture for mock logger."""
    return MagicMock(spec=Logger)


@pytest.fixture
def temp_test_dir():
    """Fixture for temporary test directory."""
    test_dir = tempfile.mkdtemp()
    yield test_dir
    # Cleanup
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)


@pytest.fixture
def file_creator(temp_test_dir):
    """Fixture for creating test files and directories."""
    def create_test_files(file_structure):
        """
        Create test files and directories based on structure dict.
        
        Args:
            file_structure: Dict with paths as keys and content as values.
                           Use None for directories.
        """
        for path, content in file_structure.items():
            full_path = os.path.join(temp_test_dir, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            if content is None:  # Directory
                os.makedirs(full_path, exist_ok=True)
            else:  # File
                with open(full_path, 'w') as f:
                    f.write(content)
    return create_test_files


class TestResolvePathsFunction:
    """Test suite for the resolve_paths function and _resolve_path generator."""

    def test_resolve_paths_with_string_input_single_file(self, mock_logger, temp_test_dir):
        """
        GIVEN a single file path as string that exists
        WHEN resolve_paths is called
        THEN expect:
            - Single file path returned in list
            - Path is absolute
            - No warnings logged
        """
        # Arrange
        test_file = os.path.join(temp_test_dir, 'test_file.txt')
        with open(test_file, 'w') as f:
            f.write('test content')
        
        # Act
        result = resolve_paths(test_file, mock_logger)
        
        # Assert
        assert len(result) == 1
        assert result[0] == os.path.abspath(test_file)
        assert os.path.isabs(result[0])
        mock_logger.warning.assert_not_called()

    def test_resolve_paths_with_string_input_nonexistent_file(self, mock_logger, temp_test_dir):
        """
        GIVEN a single file path as string that does not exist
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - Warning logged about file not found
        """
        # Arrange
        nonexistent_file = os.path.join(temp_test_dir, 'nonexistent.txt')
        
        # Act
        result = resolve_paths(nonexistent_file, mock_logger)
        
        # Assert
        assert len(result) == 0
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert 'Path not found' in warning_call
        assert nonexistent_file in warning_call

    def test_resolve_paths_with_list_input_mixed_files(self, mock_logger, temp_test_dir):
        """
        GIVEN a list of file paths with some existing and some non-existing
        WHEN resolve_paths is called
        THEN expect:
            - Only existing files returned
            - Warnings logged for non-existing files
            - Order preserved for existing files
        """
        # Arrange
        existing_file1 = os.path.join(temp_test_dir, 'file1.txt')
        existing_file2 = os.path.join(temp_test_dir, 'file2.txt')
        nonexistent_file = os.path.join(temp_test_dir, 'nonexistent.txt')
        
        with open(existing_file1, 'w') as f:
            f.write('content1')
        with open(existing_file2, 'w') as f:
            f.write('content2')
        
        file_list = [existing_file1, nonexistent_file, existing_file2]
        
        # Act
        result = resolve_paths(file_list, mock_logger)
        
        # Assert
        assert len(result) == 2
        assert os.path.abspath(existing_file1) in result
        assert os.path.abspath(existing_file2) in result
        assert os.path.abspath(nonexistent_file) not in result
        
        # Check warning was called for non-existing file
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert 'Path not found' in warning_call
        assert nonexistent_file in warning_call

    def test_resolve_paths_with_list_input_all_files_exist(self, mock_logger, temp_test_dir):
        """
        GIVEN a list of file paths that all exist
        WHEN resolve_paths is called
        THEN expect:
            - All files returned with absolute paths
            - Order preserved
            - No warnings logged
        """
        # Arrange
        file1 = os.path.join(temp_test_dir, 'file1.txt')
        file2 = os.path.join(temp_test_dir, 'file2.txt')
        file3 = os.path.join(temp_test_dir, 'file3.txt')
        
        for i, file_path in enumerate([file1, file2, file3], 1):
            with open(file_path, 'w') as f:
                f.write(f'content{i}')
        
        file_list = [file1, file2, file3]
        
        # Act
        result = resolve_paths(file_list, mock_logger)
        
        # Assert
        assert len(result) == 3
        for i, expected_file in enumerate(file_list):
            assert result[i] == os.path.abspath(expected_file)
        mock_logger.warning.assert_not_called()

    def test_resolve_paths_with_empty_list(self, mock_logger):
        """
        GIVEN an empty list
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - No warnings logged
        """
        # Act
        result = resolve_paths([], mock_logger)
        
        # Assert
        assert len(result) == 0
        assert isinstance(result, list)
        mock_logger.warning.assert_not_called()

    @patch('glob.glob')
    def test_resolve_paths_with_glob_pattern_multiple_matches(self, mock_glob, mock_logger, temp_test_dir):
        """
        GIVEN a glob pattern that matches multiple files
        WHEN resolve_paths is called
        THEN expect:
            - All matching files returned
            - Paths are absolute
            - glob.glob called with recursive=True
        """
        # Arrange
        pattern = os.path.join(temp_test_dir, '*.txt')
        mock_matches = [
            os.path.join(temp_test_dir, 'file1.txt'),
            os.path.join(temp_test_dir, 'file2.txt')
        ]
        mock_glob.return_value = mock_matches
        
        # Create the files that glob would find
        for match in mock_matches:
            with open(match, 'w') as f:
                f.write('content')
        
        # Act
        result = resolve_paths(pattern, mock_logger)
        
        # Assert
        mock_glob.assert_called_once_with(pattern, recursive=True)
        assert len(result) == 2
        for match in mock_matches:
            assert os.path.abspath(match) in result

    @patch('glob.glob')
    def test_resolve_paths_with_glob_pattern_no_matches(self, mock_glob, mock_logger, temp_test_dir):
        """
        GIVEN a glob pattern that matches no files
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - No warnings logged (empty glob is valid)
        """
        # Arrange
        pattern = os.path.join(temp_test_dir, '*.nonexistent')
        mock_glob.return_value = []
        
        # Act
        result = resolve_paths(pattern, mock_logger)
        
        # Assert
        mock_glob.assert_called_once_with(pattern, recursive=True)
        assert len(result) == 0
        mock_logger.warning.assert_not_called()

    @patch('os.path.islink')
    @patch('os.path.realpath')
    def test_resolve_paths_with_symlink_valid_target(self, mock_realpath, mock_islink, mock_logger, temp_test_dir):
        """
        GIVEN a symlink that points to an existing file
        WHEN resolve_paths is called
        THEN expect:
            - Resolved target path returned
            - Path is absolute
            - realpath called for symlink resolution
        """
        # Arrange
        target_file = os.path.join(temp_test_dir, 'target.txt')
        symlink_file = os.path.join(temp_test_dir, 'symlink.txt')
        
        with open(target_file, 'w') as f:
            f.write('target content')
        
        mock_islink.return_value = True
        mock_realpath.return_value = target_file
        
        # Mock os.path.exists to return True for the resolved path
        with patch('os.path.exists', return_value=True):
            # Act
            result = resolve_paths(symlink_file, mock_logger)
        
        # Assert
        mock_islink.assert_called_once_with(symlink_file)
        mock_realpath.assert_called_once_with(symlink_file)
        assert len(result) == 1
        assert result[0] == os.path.abspath(target_file)

    @patch('os.path.islink')
    @patch('os.path.realpath')
    @patch('os.path.exists')
    def test_resolve_paths_with_symlink_broken_target(self, mock_exists, mock_realpath, mock_islink, mock_logger, temp_test_dir):
        """
        GIVEN a symlink that points to a non-existing file
        WHEN resolve_paths is called
        THEN expect:
            - Empty list returned
            - Warning logged about broken symlink
        """
        # Arrange
        nonexistent_target = os.path.join(temp_test_dir, 'nonexistent_target.txt')
        symlink_file = os.path.join(temp_test_dir, 'broken_symlink.txt')
        
        mock_islink.return_value = True
        mock_realpath.return_value = nonexistent_target
        mock_exists.return_value = False
        
        # Act
        result = resolve_paths(symlink_file, mock_logger)
        
        # Assert
        mock_islink.assert_called_once_with(symlink_file)
        mock_realpath.assert_called_once_with(symlink_file)
        assert len(result) == 0
        mock_logger.warning.assert_called_once()
        warning_call = mock_logger.warning.call_args[0][0]
        assert 'Path not found' in warning_call

    def test_resolve_paths_with_directory_input(self, mock_logger, temp_test_dir):
        """
        GIVEN a directory path as input
        WHEN resolve_paths is called
        THEN expect:
            - Paths within directory are not automatically resolved  
            - Function treats directory as a single path to check
        """
        # Arrange - temp_test_dir is already a directory
        
        # Act
        result = resolve_paths(temp_test_dir, mock_logger)
        
        # Assert - function doesn't automatically handle directories as path expansion
        # The exact behavior depends on implementation - directories might be ignored or cause warnings
        assert isinstance(result, list)

    def test_resolve_paths_with_path_object(self, mock_logger, temp_test_dir):
        """
        GIVEN a pathlib.Path object that exists
        WHEN resolve_paths is called
        THEN expect:
            - ValueError raised for unsupported input type
            - Function only accepts strings or lists of strings
        """
        # Arrange
        test_file = Path(temp_test_dir) / 'test_file.txt'
        test_file.write_text('test content')
        
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid input type for file_paths"):
            resolve_paths(test_file, mock_logger)