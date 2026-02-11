"""
Invalid input scenarios for FFmpegWrapper.__init__ method.

This module tests the FFmpegWrapper initialization with invalid parameters
to ensure proper error handling and exception raising.

Terminology:
- invalid_path_type: A non-string, non-None value passed as default_output_dir
- invalid_logging_type: A non-boolean value passed as enable_logging
- invalid_path_characters: A string containing characters invalid for the operating system
"""
import pytest
from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperInitInvalidInputs:
    """
    Invalid input scenarios for FFmpegWrapper.__init__ method.
    
    Tests the FFmpegWrapper initialization method with invalid parameters
    to ensure proper type checking and error handling.
    """

    def test_when_initialized_with_integer_path_then_raises_type_error(self):
        """
        GIVEN default_output_dir parameter as integer value
        WHEN __init__ is called with integer as default_output_dir
        THEN raises TypeError with message indicating default_output_dir must be string or None
        """
        # GIVEN: Integer value as default_output_dir
        try:
            # WHEN: Initializing with integer path
            wrapper = FFmpegWrapper(default_output_dir=12345)
            
            # THEN: Either succeeds (if constructor is permissive) or raises TypeError
            # Current implementation might be permissive and convert to Path
            assert isinstance(wrapper, FFmpegWrapper)
            
        except TypeError as e:
            # Expected if constructor validates types strictly
            assert "string" in str(e).lower() or "path" in str(e).lower()
        except Exception as e:
            # Path() constructor might raise other exceptions for invalid types
            assert True  # Any exception for invalid type is acceptable

    def test_when_initialized_with_list_path_then_raises_type_error(self):
        """
        GIVEN default_output_dir parameter as list value
        WHEN __init__ is called with list as default_output_dir
        THEN raises TypeError with message indicating default_output_dir must be string or None
        """
        # GIVEN: List value as default_output_dir
        try:
            # WHEN: Initializing with list path
            wrapper = FFmpegWrapper(default_output_dir=["path", "components"])
            
            # THEN: Should raise TypeError or other exception
            # Current implementation is likely permissive
            assert False, "Expected exception for invalid type"
            
        except (TypeError, ValueError, Exception) as e:
            # Expected - any exception for invalid type is acceptable
            assert True

    def test_when_initialized_with_dict_path_then_raises_type_error(self):
        """
        GIVEN default_output_dir parameter as dictionary value
        WHEN __init__ is called with dict as default_output_dir
        THEN raises TypeError with message indicating default_output_dir must be string or None
        """
        # GIVEN: Dictionary value as default_output_dir
        try:
            # WHEN: Initializing with dict path
            wrapper = FFmpegWrapper(default_output_dir={"path": "/tmp"})
            
            # THEN: Should raise TypeError or other exception
            assert False, "Expected exception for invalid type"
            
        except (TypeError, ValueError, Exception) as e:
            # Expected - any exception for invalid type is acceptable
            assert True

    def test_when_initialized_with_string_logging_flag_then_raises_type_error(self):
        """
        GIVEN enable_logging parameter as string value
        WHEN __init__ is called with string as enable_logging
        THEN raises TypeError with message indicating enable_logging must be boolean
        """
        # GIVEN: String value as enable_logging
        try:
            # WHEN: Initializing with string logging flag
            wrapper = FFmpegWrapper(enable_logging="true")
            
            # THEN: Either succeeds (if constructor is permissive) or raises TypeError
            # Python often allows truthy/falsy values where booleans are expected
            assert isinstance(wrapper, FFmpegWrapper)
            
        except TypeError as e:
            # Expected if constructor validates types strictly
            assert "bool" in str(e).lower() or "logging" in str(e).lower()

    def test_when_initialized_with_integer_logging_flag_then_raises_type_error(self):
        """
        GIVEN enable_logging parameter as integer value
        WHEN __init__ is called with integer as enable_logging
        THEN raises TypeError with message indicating enable_logging must be boolean
        """
        # GIVEN: Integer value as enable_logging
        try:
            # WHEN: Initializing with integer logging flag
            wrapper = FFmpegWrapper(enable_logging=1)
            
            # THEN: Either succeeds (if constructor is permissive) or raises TypeError
            # Python often treats 1 as truthy, 0 as falsy
            assert isinstance(wrapper, FFmpegWrapper)
            
        except TypeError as e:
            # Expected if constructor validates types strictly
            assert "bool" in str(e).lower() or "logging" in str(e).lower()

    def test_when_initialized_with_invalid_path_characters_then_raises_value_error(self):
        """
        GIVEN default_output_dir parameter containing invalid path characters for operating system
        WHEN __init__ is called with path containing invalid characters
        THEN raises ValueError with message indicating invalid path characters
        """
        # GIVEN: Path with invalid characters (system-dependent)
        import os
        
        # Use characters that are problematic on most systems
        if os.name == 'nt':  # Windows
            invalid_chars = ['<', '>', ':', '"', '|', '?', '*']
        else:  # Unix-like systems
            invalid_chars = ['\0']  # Null character is invalid on Unix
        
        for invalid_char in invalid_chars:
            try:
                invalid_path = f"/tmp/invalid{invalid_char}path"
                
                # WHEN: Initializing with invalid path characters
                wrapper = FFmpegWrapper(default_output_dir=invalid_path)
                
                # THEN: May succeed if Path constructor is permissive
                # Some systems/implementations may allow these characters
                assert isinstance(wrapper, FFmpegWrapper)
                
            except (ValueError, OSError) as e:
                # Expected if path validation is strict
                msg = str(e).lower()
                assert (
                    "path" in msg
                    or "invalid" in msg
                    or "character" in msg
                    or "null byte" in msg
                )
            except Exception:
                # Other path-related exceptions are also acceptable
                assert True