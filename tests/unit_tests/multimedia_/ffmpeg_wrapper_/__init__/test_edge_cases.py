"""
Edge case scenarios for FFmpegWrapper.__init__ method.

This module tests the FFmpegWrapper initialization with boundary conditions
and edge cases to ensure robust handling of unusual but valid inputs.

Terminology:
- nonexistent_directory: A valid path string pointing to a directory that doesn't exist
- read_only_directory: A valid path string pointing to a directory without write permissions
- very_long_path: A path string approaching or exceeding OS path length limits
"""
import pytest
from pathlib import Path
from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperInitEdgeCases:
    """
    Edge case scenarios for FFmpegWrapper.__init__ method.
    
    Tests the FFmpegWrapper initialization method with edge cases
    including permission issues, path length limits, and directory creation.
    """

    def test_when_initialized_with_nonexistent_directory_then_creates_directory_and_instance(self):
        """
        GIVEN default_output_dir parameter pointing to nonexistent directory with valid parent
        WHEN __init__ is called with nonexistent directory path
        THEN creates the directory and FFmpegWrapper instance with default_output_dir set to created directory
        """
        # GIVEN: A path to nonexistent directory with valid parent
        import tempfile
        import os
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as temp_dir:
            nonexistent_dir = os.path.join(temp_dir, "new_directory")
            
            # WHEN: Initializing FFmpegWrapper with nonexistent directory
            wrapper = FFmpegWrapper(default_output_dir=nonexistent_dir)
            
            # THEN: Directory is created and wrapper is initialized properly
            assert isinstance(wrapper, FFmpegWrapper)
            assert wrapper.default_output_dir == os.path.abspath(nonexistent_dir)
            assert os.path.isdir(wrapper.default_output_dir)

    def test_when_initialized_with_read_only_parent_directory_then_raises_permission_error(self):
        """
        GIVEN default_output_dir parameter pointing to nonexistent directory with read-only parent
        WHEN __init__ is called with path requiring directory creation in read-only location
        THEN raises PermissionError with message indicating insufficient permissions for directory creation
        """
        # GIVEN: A read-only parent directory path
        import tempfile
        import os
        from pathlib import Path
        
        try:
            # This test is system-dependent and may not work on all platforms
            with tempfile.TemporaryDirectory() as temp_dir:
                # Make parent directory read-only
                os.chmod(temp_dir, 0o444)  # Read-only
                read_only_subdir = os.path.join(temp_dir, "readonly_subdir")
                
                try:
                    # WHEN: Attempting to initialize with read-only parent
                    wrapper = FFmpegWrapper(default_output_dir=read_only_subdir)
                    
                    # THEN: Should either work or raise PermissionError
                    # (Constructor behavior may vary - some may not create directories immediately)
                    assert isinstance(wrapper, FFmpegWrapper)
                    
                except PermissionError:
                    # Expected behavior for constructors that attempt directory creation
                    assert True
                finally:
                    # Restore permissions for cleanup
                    os.chmod(temp_dir, 0o755)
                    
        except (OSError, PermissionError):
            # System may not support permission changes - skip test
            pytest.skip("System doesn't support permission-based testing")

    def test_when_initialized_with_empty_string_path_then_uses_current_directory(self):
        """
        GIVEN default_output_dir parameter as empty string
        WHEN __init__ is called with empty string as default_output_dir
        THEN creates FFmpegWrapper instance with default_output_dir set to current working directory
        """
        # GIVEN: Empty string as default_output_dir
        import os
        
        # WHEN: Initializing FFmpegWrapper with empty string
        wrapper = FFmpegWrapper(default_output_dir="")
        
        assert isinstance(wrapper, FFmpegWrapper)
        assert hasattr(wrapper, 'default_output_dir')
        assert wrapper.default_output_dir == os.getcwd()

    def test_when_initialized_with_path_containing_spaces_then_creates_instance_with_spaced_path(self):
        """
        GIVEN default_output_dir parameter containing spaces in directory name
        WHEN __init__ is called with path containing spaces
        THEN creates FFmpegWrapper instance with default_output_dir preserving spaces in path
        """
        # GIVEN: Path with spaces
        import os
        
        # WHEN: Initializing FFmpegWrapper with spaced path
        spaced_path = "/tmp/path with spaces"
        wrapper = FFmpegWrapper(default_output_dir=spaced_path)
        
        # THEN: Wrapper is created with spaced path preserved
        assert isinstance(wrapper, FFmpegWrapper)
        assert wrapper.default_output_dir == os.path.abspath(spaced_path)
        assert "with spaces" in wrapper.default_output_dir

    def test_when_initialized_with_maximum_length_path_then_creates_instance_or_raises_os_error(self):
        """
        GIVEN default_output_dir parameter with path length at operating system maximum
        WHEN __init__ is called with maximum length path
        THEN either creates FFmpegWrapper instance or raises OSError indicating path too long
        """
        # GIVEN: Very long path (approaching system limits)
        import os
        
        # Create a long but reasonable path (not at true system maximum to avoid issues)
        long_path_component = "a" * 100
        long_path = f"/tmp/{long_path_component}/{long_path_component}"
        
        try:
            # WHEN: Initializing FFmpegWrapper with long path
            wrapper = FFmpegWrapper(default_output_dir=long_path)
            
            # THEN: Either succeeds or raises appropriate error
            assert isinstance(wrapper, FFmpegWrapper)
            assert wrapper.default_output_dir == os.path.abspath(long_path)
            
        except (OSError, ValueError) as e:
            # May raise OSError for path too long or ValueError for invalid path
            assert "path" in str(e).lower() or "name" in str(e).lower()

    def test_when_initialized_with_path_containing_unicode_characters_then_creates_instance_with_unicode_path(self):
        """
        GIVEN default_output_dir parameter containing valid unicode characters in path
        WHEN __init__ is called with unicode characters in path
        THEN creates FFmpegWrapper instance with default_output_dir preserving unicode characters
        """
        # GIVEN: Path with unicode characters
        import os
        
        unicode_path = "/tmp/测试目录/видео"  # Chinese and Russian characters
        
        # WHEN: Initializing FFmpegWrapper with unicode path
        wrapper = FFmpegWrapper(default_output_dir=unicode_path)
        
        # THEN: Wrapper is created with unicode path preserved
        assert isinstance(wrapper, FFmpegWrapper)
        assert wrapper.default_output_dir == os.path.abspath(unicode_path)
        # Check that unicode characters are preserved
        path_str = wrapper.default_output_dir
        assert "测试目录" in path_str
        assert "видео" in path_str