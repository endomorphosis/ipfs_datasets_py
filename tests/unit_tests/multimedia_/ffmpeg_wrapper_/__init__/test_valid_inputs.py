"""
Valid input scenarios for FFmpegWrapper.__init__ method.

This module tests the FFmpegWrapper initialization with valid parameters
to ensure proper object construction and attribute assignment.

Terminology:
- valid_output_dir: A string path that represents a valid, accessible directory
- valid_logging_flag: A boolean value (True or False)
"""
import pytest
from pathlib import Path
from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperInitValidInputs:
    """
    Valid input scenarios for FFmpegWrapper.__init__ method.
    
    Tests the FFmpegWrapper initialization method with valid parameters
    to ensure proper object construction and default value handling.
    """

    def test_when_initialized_with_default_parameters_then_creates_instance_with_current_directory(self):
        """
        GIVEN no parameters provided to FFmpegWrapper constructor
        WHEN __init__ is called with default parameters
        THEN creates FFmpegWrapper instance with default_output_dir set to current working directory
        """
        # Since FFmpegWrapper.__init__ has a working implementation, test actual behavior
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        import os
        
        # Create wrapper with default parameters
        wrapper = FFmpegWrapper()
        
        # Verify instance was created successfully
        assert wrapper is not None
        assert hasattr(wrapper, 'default_output_dir')
        
        # Verify default_output_dir is set to current working directory
        assert wrapper.default_output_dir == os.getcwd()

    def test_when_initialized_with_valid_absolute_path_then_creates_instance_with_specified_directory(self):
        """
        GIVEN a valid absolute path string as default_output_dir parameter
        WHEN __init__ is called with valid absolute path
        THEN creates FFmpegWrapper instance with default_output_dir set to specified absolute path
        """
        # Since FFmpegWrapper.__init__ has a working implementation, test with absolute path
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        import os
        
        # Use a valid absolute path
        test_path = "/tmp/test_output"
        
        # Create wrapper with absolute path
        wrapper = FFmpegWrapper(default_output_dir=test_path)
        
        # Verify instance was created successfully
        assert wrapper is not None
        assert hasattr(wrapper, 'default_output_dir')
        
        # Verify default_output_dir is set to the specified path
        assert wrapper.default_output_dir == test_path

    def test_when_initialized_with_valid_relative_path_then_creates_instance_with_resolved_absolute_path(self):
        """
        GIVEN a valid relative path string as default_output_dir parameter
        WHEN __init__ is called with valid relative path
        THEN creates FFmpegWrapper instance with default_output_dir resolved to absolute path
        """
        # Since FFmpegWrapper.__init__ has a working implementation, test with relative path
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        import os
        
        # Use a relative path
        relative_path = "test_output"
        
        # Create wrapper with relative path
        wrapper = FFmpegWrapper(default_output_dir=relative_path)
        
        # Verify instance was created successfully
        assert wrapper is not None
        assert hasattr(wrapper, 'default_output_dir')
        
        # Verify default_output_dir is resolved to absolute path
        expected_absolute_path = os.path.abspath(relative_path)
        assert wrapper.default_output_dir == expected_absolute_path

    def test_when_initialized_with_logging_enabled_then_creates_instance_with_logging_true(self):
        """
        GIVEN enable_logging parameter set to True
        WHEN __init__ is called with enable_logging=True
        THEN creates FFmpegWrapper instance with enable_logging attribute set to True
        """
        # Since FFmpegWrapper.__init__ has a working implementation, test logging parameter
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        
        # Create wrapper with logging enabled
        wrapper = FFmpegWrapper(enable_logging=True)
        
        # Verify instance was created successfully
        assert wrapper is not None
        assert hasattr(wrapper, 'enable_logging')
        
        # Verify logging is enabled
        assert wrapper.enable_logging == True

    def test_when_initialized_with_logging_disabled_then_creates_instance_with_logging_false(self):
        """
        GIVEN enable_logging parameter set to False
        WHEN __init__ is called with enable_logging=False
        THEN creates FFmpegWrapper instance with enable_logging attribute set to False
        """
        # Since FFmpegWrapper.__init__ has a working implementation, test logging disabled
        from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper
        
        # Create wrapper with logging disabled
        wrapper = FFmpegWrapper(enable_logging=False)
        
        # Verify instance was created successfully
        assert wrapper is not None
        assert hasattr(wrapper, 'enable_logging')
        
        # Verify logging is disabled
        assert wrapper.enable_logging == False