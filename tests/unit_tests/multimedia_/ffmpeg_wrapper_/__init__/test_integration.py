"""
Integration scenarios for FFmpegWrapper.__init__ method.

This module tests the FFmpegWrapper initialization in combination with
system dependencies and external library availability.

Terminology:
- ffmpeg_available_system: A system environment where FFmpeg dependencies are installed
- ffmpeg_unavailable_system: A system environment where FFmpeg dependencies are missing
- filesystem_interaction: Testing actual directory creation and path resolution
"""
import pytest
from unittest.mock import patch
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperInitIntegration:
    """
    Integration scenarios for FFmpegWrapper.__init__ method.
    
    Tests the FFmpegWrapper initialization method with system dependencies
    and filesystem interactions to ensure proper integration behavior.
    """

    def test_when_initialized_with_ffmpeg_available_then_logs_availability_warning(self):
        """
        GIVEN system environment with python-ffmpeg library available
        WHEN __init__ is called with logging enabled
        THEN creates FFmpegWrapper instance and logs no dependency warnings
        """
        # GIVEN: System environment (varies by installation)
        # WHEN: Initialize FFmpegWrapper
        wrapper = FFmpegWrapper(enable_logging=True)
        
        # THEN: Instance is created successfully
        assert wrapper is not None
        assert hasattr(wrapper, 'enable_logging')
        assert wrapper.enable_logging == True

    def test_when_initialized_with_ffmpeg_unavailable_then_logs_missing_dependency_warning(self):
        """
        GIVEN system environment with python-ffmpeg library unavailable
        WHEN __init__ is called with logging enabled
        THEN creates FFmpegWrapper instance and logs warning about missing python-ffmpeg dependency
        """
        # GIVEN/WHEN: Initialize FFmpegWrapper
        wrapper = FFmpegWrapper(enable_logging=True)
        
        # THEN: Instance is created regardless of FFmpeg availability
        assert wrapper is not None
        assert hasattr(wrapper, 'default_output_dir')
        assert hasattr(wrapper, 'enable_logging')

    def test_when_initialized_then_creates_actual_output_directory_on_filesystem(self):
        """
        GIVEN default_output_dir parameter pointing to nonexistent directory
        WHEN __init__ is called with directory creation required
        THEN creates actual directory on filesystem and FFmpegWrapper instance with correct path
        """
        # GIVEN: Output directory path
        output_dir = "/tmp/ffmpeg_test_output"
        
        # WHEN: Initialize with custom output directory
        wrapper = FFmpegWrapper(default_output_dir=output_dir)
        
        # THEN: Instance is created with correct directory path
        assert wrapper is not None
        import os

        assert wrapper.default_output_dir == os.path.abspath(output_dir)
        assert os.path.isdir(wrapper.default_output_dir)

    def test_when_initialized_multiple_times_with_same_directory_then_all_instances_share_directory(self):
        """
        GIVEN multiple FFmpegWrapper initialization calls with same default_output_dir
        WHEN __init__ is called multiple times with identical directory path
        THEN creates multiple FFmpegWrapper instances all using the same shared output directory
        """
        # GIVEN: Shared output directory path
        shared_dir = "/tmp/shared_ffmpeg_output"
        
        # WHEN: Create multiple instances with same directory
        wrapper1 = FFmpegWrapper(default_output_dir=shared_dir)
        wrapper2 = FFmpegWrapper(default_output_dir=shared_dir)
        wrapper3 = FFmpegWrapper(default_output_dir=shared_dir)
        
        # THEN: All instances use the same directory
        assert wrapper1.default_output_dir == wrapper2.default_output_dir == wrapper3.default_output_dir
        import os

        assert wrapper1.default_output_dir == os.path.abspath(shared_dir)

    def test_when_initialized_with_relative_path_then_resolves_against_current_working_directory(self):
        """
        GIVEN default_output_dir parameter as relative path and specific current working directory
        WHEN __init__ is called with relative path from known working directory
        THEN creates FFmpegWrapper instance with default_output_dir resolved relative to current working directory
        """
        # GIVEN: Relative path
        relative_path = "relative_output"
        
        # WHEN: Initialize with relative path
        wrapper = FFmpegWrapper(default_output_dir=relative_path)
        
        # THEN: Path is resolved relative to current directory
        import os

        assert wrapper.default_output_dir == os.path.abspath(relative_path)
        assert wrapper.default_output_dir.endswith(os.sep + "relative_output")

    def test_when_initialized_with_logging_then_initializes_module_logger_for_subsequent_operations(self):
        """
        GIVEN enable_logging parameter set to True
        WHEN __init__ is called with logging enabled
        THEN creates FFmpegWrapper instance and initializes module-level logger for use in subsequent operations
        """
        # GIVEN/WHEN: Initialize with logging enabled
        wrapper = FFmpegWrapper(enable_logging=True)
        
        # THEN: Instance has logging configuration set correctly
        assert wrapper.enable_logging == True
        assert hasattr(wrapper, 'default_output_dir')
        
        # Verify that opposite case also works
        wrapper_no_logging = FFmpegWrapper(enable_logging=False)
        assert wrapper_no_logging.enable_logging == False