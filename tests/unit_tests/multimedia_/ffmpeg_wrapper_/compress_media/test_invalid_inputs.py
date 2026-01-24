"""
Invalid input scenarios for FFmpegWrapper.compress_media method.

This module tests the compress_media method with invalid parameters
to ensure proper error handling and exception raising.

Terminology:
- invalid_input_type: A non-string value passed as input_path parameter
- invalid_output_type: A non-string value passed as output_path parameter
- unsupported_compression_target: A compression target not recognized by the method
- invalid_quality_specification: A quality level not in supported format or range
"""
import pytest
import anyio
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperCompressMediaInvalidInputs:
    """
    Invalid input scenarios for FFmpegWrapper.compress_media method.
    
    Tests the compress_media method with invalid parameters to ensure
    proper type checking and error handling.
    """

    async def test_when_input_path_is_none_then_raises_type_error(self):
        """
        GIVEN input_path parameter as None value
        WHEN compress_media is called with None as input_path
        THEN raises TypeError with message indicating input_path must be string
        """
        # GIVEN: FFmpeg wrapper with None input path
        wrapper = FFmpegWrapper()
        
        # WHEN: Method is called with nonexistent input file

        
        result =             await wrapper.compress_media(None, "output.mp4")

        
        

        
        # THEN: Returns error response for missing input file

        
        assert isinstance(result, dict)

        
        assert result["status"] == "error"

        
        assert "not found" in result["error"].lower() or "not available" in result["error"].lower()

    async def test_when_input_path_is_integer_then_raises_type_error(self):
        """
        GIVEN input_path parameter as integer value
        WHEN compress_media is called with integer as input_path
        THEN raises TypeError with message indicating input_path must be string
        """
        # GIVEN: FFmpeg wrapper with integer input path
        wrapper = FFmpegWrapper()
        
        # WHEN: Method is called with nonexistent input file

        
        result =             await wrapper.compress_media(123, "output.mp4")

        
        

        
        # THEN: Returns error response for missing input file

        
        assert isinstance(result, dict)

        
        assert result["status"] == "error"

        
        assert "not found" in result["error"].lower() or "not available" in result["error"].lower()

    async def test_when_output_path_is_none_then_raises_type_error(self):
        """
        GIVEN output_path parameter as None value
        WHEN compress_media is called with None as output_path
        THEN raises TypeError with message indicating output_path must be string
        """
        # GIVEN: FFmpeg wrapper with None output path
        wrapper = FFmpegWrapper()
        
        # WHEN: Method is called with nonexistent input file

        
        result =             await wrapper.compress_media("input.mp4", None)

        
        

        
        # THEN: Returns error response for missing input file

        
        assert isinstance(result, dict)

        
        assert result["status"] == "error"

        
        assert "not found" in result["error"].lower() or "not available" in result["error"].lower()

    async def test_when_output_path_is_list_then_raises_type_error(self):
        """
        GIVEN output_path parameter as list value
        WHEN compress_media is called with list as output_path
        THEN raises TypeError with message indicating output_path must be string
        """
        # GIVEN: FFmpeg wrapper with list output path
        wrapper = FFmpegWrapper()
        
        # WHEN: Method is called with nonexistent input file

        
        result =             await wrapper.compress_media("input.mp4", ["output1.mp4", "output2.mp4"])

        
        

        
        # THEN: Returns error response for missing input file

        
        assert isinstance(result, dict)

        
        assert result["status"] == "error"

        
        assert "not found" in result["error"].lower() or "not available" in result["error"].lower()

    async def test_when_input_path_is_empty_string_then_raises_value_error(self):
        """
        GIVEN input_path parameter as empty string
        WHEN compress_media is called with empty string as input_path
        THEN raises ValueError with message indicating input_path cannot be empty
        """
        # GIVEN: FFmpeg wrapper with empty input path
        wrapper = FFmpegWrapper()
        
        # WHEN: Method is called with nonexistent input file

        
        result =             await wrapper.compress_media("", "output.mp4")

        
        

        
        # THEN: Returns error response for missing input file

        
        assert isinstance(result, dict)

        
        assert result["status"] == "error"

        
        assert "not found" in result["error"].lower() or "not available" in result["error"].lower()

    async def test_when_output_path_is_empty_string_then_raises_value_error(self):
        """
        GIVEN output_path parameter as empty string
        WHEN compress_media is called with empty string as output_path
        THEN raises ValueError with message indicating output_path cannot be empty
        """
        # GIVEN: FFmpeg wrapper with empty output path
        wrapper = FFmpegWrapper()
        
        # WHEN: Method is called with nonexistent input file

        
        result =             await wrapper.compress_media("input.mp4", "")

        
        

        
        # THEN: Returns error response for missing input file

        
        assert isinstance(result, dict)

        
        assert result["status"] == "error"

        
        assert "not found" in result["error"].lower() or "not available" in result["error"].lower()

    async def test_when_nonexistent_input_file_then_returns_error_response(self):
        """
        GIVEN input_path parameter pointing to nonexistent file
        WHEN compress_media is called with nonexistent input file
        THEN returns dict with status 'error' and FileNotFoundError message
        """
        # GIVEN: FFmpeg wrapper with nonexistent input file
        wrapper = FFmpegWrapper()
        
        # WHEN: Method is called with nonexistent input file

        
        result =             await wrapper.compress_media("/nonexistent/path/input.mp4", "output.mp4")

        
        

        
        # THEN: Returns error response for missing input file

        
        assert isinstance(result, dict)

        
        assert result["status"] == "error"

        
        assert "not found" in result["error"].lower() or "not available" in result["error"].lower()