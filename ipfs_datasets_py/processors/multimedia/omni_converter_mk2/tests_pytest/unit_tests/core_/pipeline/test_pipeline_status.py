"""
Test suite for core/_pipeline_status.py converted from unittest to pytest.

This module tests the PipelineStatus class which tracks the progress and state
of file processing through the pipeline.
"""
import pytest
from unittest.mock import MagicMock
import json
import os
import shutil
import tempfile
from pathlib import Path

try:
    from pydantic import ValidationError
except ImportError:
    pytest.skip("Pydantic is required for this test suite. Please install it with 'pip install pydantic'.", 
                allow_module_level=True)

from core._pipeline_status import PipelineStatus


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_files(temp_dir):
    """Create test files in temporary directory."""
    test_file_path = os.path.join(temp_dir, "test_file.txt")
    with open(test_file_path, 'w') as f:
        f.write("Test content")
    
    large_file_path = os.path.join(temp_dir, "large_file.txt")
    with open(large_file_path, 'w') as f:
        f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)

    executable_file_path = os.path.join(temp_dir, "test_script.sh")
    with open(executable_file_path, 'w') as f:
        f.write("#!/bin/sh\necho 'Hello, world!'")

    return {
        'test_file_path': test_file_path,
        'large_file_path': large_file_path,
        'executable_file_path': executable_file_path
    }


@pytest.mark.unit
class TestPipelineStatusInitialization:
    """Test PipelineStatus initialization and validation."""

    def test_default_initialization(self):
        """
        GIVEN no arguments
        WHEN PipelineStatus() is instantiated
        THEN expect:
            - total_files = 0
            - successful_files = 0
            - failed_files = 0
            - current_file = ""
            - is_processing = False
        """
        status = PipelineStatus()
        
        assert status.total_files == 0
        assert status.successful_files == 0
        assert status.failed_files == 0
        assert status.current_file == ""
        assert status.is_processing is False

    def test_initialization_with_all_parameters(self, test_files):
        """
        GIVEN all valid parameters
        WHEN PipelineStatus is instantiated with specific values
        THEN expect:
            - All attributes match the provided values
            - Instance is created successfully
        """
        status = PipelineStatus(
            total_files=10,
            successful_files=7,
            failed_files=2,
            current_file=test_files['test_file_path'],
            is_processing=True
        )
        
        assert status.total_files == 10
        assert status.successful_files == 7
        assert status.failed_files == 2
        assert status.current_file == Path(test_files['test_file_path'])
        assert status.is_processing is True
    
    def test_initialization_with_partial_parameters(self):
        """
        GIVEN only some parameters
        WHEN PipelineStatus is instantiated with partial values
        THEN expect:
            - Provided attributes match the given values
            - Unprovided attributes use default values
        """
        status = PipelineStatus(total_files=5, is_processing=True)
        
        assert status.total_files == 5
        assert status.successful_files == 0  # default
        assert status.failed_files == 0      # default
        assert status.current_file == ""     # default
        assert status.is_processing is True
    
    def test_initialization_with_invalid_types(self):
        """
        GIVEN invalid parameter types
        WHEN PipelineStatus is instantiated with wrong types
        THEN expect:
            - ValidationError is raised
            - Error message indicates type mismatch
        """
        with pytest.raises(ValidationError) as exc_info:
            PipelineStatus(total_files="not_a_number")
        
        error_details = str(exc_info.value)
        assert "total_files" in error_details
        
        with pytest.raises(ValidationError):
            PipelineStatus(is_processing="not_a_boolean")
        
        with pytest.raises(ValidationError):
            PipelineStatus(current_file=123)
    
    def test_initialization_with_negative_file_counts(self):
        """
        GIVEN negative values for file counts
        WHEN PipelineStatus is instantiated with negative numbers
        THEN expect:
            - Either ValidationError is raised OR
            - Values are accepted (depending on validation rules)
        """
        # Test if negative values are accepted or rejected
        try:
            status = PipelineStatus(
                total_files=-1,
                successful_files=-2,
                failed_files=-3
            )
            # If accepted, verify they are stored as-is
            assert status.total_files == -1
            assert status.successful_files == -2
            assert status.failed_files == -3
        except ValidationError:
            # If validation rejects negative values, that's also valid behavior
            pass


@pytest.mark.unit 
class TestPipelineStatusBasicOperations:
    """Test basic operations on PipelineStatus."""

    def test_to_dict_default_values(self):
        """Test to_dict() with default values."""
        status = PipelineStatus()
        result = status.to_dict()
        
        assert isinstance(result, dict)
        assert result["total_files"] == 0
        assert result["successful_files"] == 0
        assert result["failed_files"] == 0
        assert result["current_file"] == ""
        assert result["is_processing"] is False

    def test_to_dict_with_values(self, test_files):
        """Test to_dict() with specific values."""
        status = PipelineStatus(
            total_files=5,
            successful_files=3,
            failed_files=1,
            current_file=test_files['test_file_path'],
            is_processing=True
        )
        result = status.to_dict()
        
        assert result["total_files"] == 5
        assert result["successful_files"] == 3
        assert result["failed_files"] == 1
        assert str(result["current_file"]) == str(Path(test_files['test_file_path']))
        assert result["is_processing"] is True

    def test_str_representation(self, test_files):
        """Test string representation of PipelineStatus."""
        status = PipelineStatus(
            total_files=10,
            successful_files=6,
            failed_files=2,
            current_file=test_files['test_file_path'],
            is_processing=True
        )
        
        str_repr = str(status)
        assert "total_files=10" in str_repr
        assert "successful_files=6" in str_repr
        assert "failed_files=2" in str_repr
        
    def test_progress_calculation(self):
        """Test progress calculation methods if they exist."""
        status = PipelineStatus(
            total_files=10,
            successful_files=6,
            failed_files=2
        )
        
        # If there's a progress property or method, test it
        if hasattr(status, 'progress'):
            progress = status.progress
            assert isinstance(progress, (int, float))
            assert 0 <= progress <= 1  # Progress should be between 0 and 1
        
        # Test completion status
        if hasattr(status, 'is_complete'):
            # When processing 8 out of 10 files, should not be complete
            assert status.is_complete is False
            
            # When all files are processed
            status.successful_files = 8
            status.failed_files = 2
            if hasattr(status, 'is_complete'):
                assert status.is_complete is True