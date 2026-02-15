"""
Pytest configuration and fixtures for the test suite.
"""

import pytest
import tempfile
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from typing import Protocol


@pytest.fixture
def temp_dir():
    """Create a temporary directory that gets cleaned up after test."""
    temp_directory = tempfile.mkdtemp()
    yield temp_directory
    shutil.rmtree(temp_directory, ignore_errors=True)


@pytest.fixture
def temp_file(temp_dir):
    """Create a temporary file that gets cleaned up after test."""
    file_path = os.path.join(temp_dir, "test_file.txt")
    with open(file_path, 'w') as f:
        f.write("test content")
    return file_path


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing."""
    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock() 
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.critical = MagicMock()
    return logger


@pytest.fixture
def sample_files(temp_dir):
    """Create a set of sample files for testing."""
    files = {}
    
    # Create various file types
    files['txt'] = os.path.join(temp_dir, "sample.txt")
    with open(files['txt'], 'w') as f:
        f.write("Sample text content")
        
    files['json'] = os.path.join(temp_dir, "sample.json")
    with open(files['json'], 'w') as f:
        f.write('{"key": "value"}')
        
    files['md'] = os.path.join(temp_dir, "sample.md")
    with open(files['md'], 'w') as f:
        f.write("# Sample Markdown\n\nContent here.")
    
    return files


@pytest.fixture
def nested_dir_structure(temp_dir):
    """Create a nested directory structure for testing."""
    structure = {
        'root': temp_dir,
        'subdir1': os.path.join(temp_dir, 'subdir1'),
        'subdir2': os.path.join(temp_dir, 'subdir2'),
        'nested': os.path.join(temp_dir, 'subdir1', 'nested')
    }
    
    # Create directories
    for dir_path in [structure['subdir1'], structure['subdir2'], structure['nested']]:
        os.makedirs(dir_path, exist_ok=True)
    
    # Create files in each directory
    structure['files'] = []
    for i, dir_key in enumerate(['root', 'subdir1', 'subdir2', 'nested']):
        file_path = os.path.join(structure[dir_key], f'file{i}.txt')
        with open(file_path, 'w') as f:
            f.write(f"Content for file {i}")
        structure['files'].append(file_path)
    
    return structure