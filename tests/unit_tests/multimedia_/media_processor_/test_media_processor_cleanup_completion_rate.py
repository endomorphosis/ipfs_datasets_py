#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import os
import asyncio
import tempfile
import uuid
import re
import time
from unittest.mock import MagicMock, AsyncMock
from typing import Dict, Any, Coroutine
import inspect
from pathlib import Path

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/multimedia/media_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/multimedia/media_processor_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

# Import the MediaProcessor class and its class dependencies
from ipfs_datasets_py.multimedia.media_processor import MediaProcessor, make_media_processor
from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper

# Import the factory
from tests.unit_tests.multimedia_.media_processor_.media_processor_factory_mk2 import (
    MediaProcessorTestDataFactory
)
from tests.unit_tests.multimedia_.ffmpeg_wrapper_.ffmpeg_wrapper_test_data_factory import (
    FFmpegWrapperTestDataFactory
)
from tests.unit_tests.multimedia_.ffmpeg_wrapper_.ffmpeg_wrapper_test_data_factory import (
    FFmpegWrapperTestDataFactory
)



# Check if each class's methods are accessible:
assert MediaProcessor.download_and_convert 
assert MediaProcessor.get_capabilities

assert isinstance(MediaProcessor.download_and_convert, Coroutine)

# Check if the classes' attributes are present
for attr in ['default_output_dir ', 'enable_logging', 'logger', 'ytdlp', 'ffmpeg ']:
    assert hasattr(MediaProcessor, attr), f"MediaProcessor is missing attribute: {attr}"

# Check if the classes have their relevant public methods accessible
assert YtDlpWrapper.download_video
assert isinstance(YtDlpWrapper.download_video, Coroutine)

assert FFmpegWrapper.convert_video
assert isinstance(FFmpegWrapper.convert_video, Coroutine)

# Check if the each method's signatures and annotations are correct
for attr, annotation in{
                        'url': str,
                        'output_format': str,
                        'quality': str,
                        'return': Dict[str, Any]
                    }.items():
    assert annotation in inspect.get_annotations(
        getattr(MediaProcessor.download_and_convert, attr)
    ), f"annotation '{attr}' is missing or incorrect in MediaProcessor"

assert inspect.get_annotations(MediaProcessor.get_capabilities) == {
    'return': Dict[str, Any]
}

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

# Check if the module's imports are available
try:
    import asyncio
    import logging
    from typing import Dict, List, Any, Optional, Union
    from pathlib import Path
    from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper
    from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper
except ImportError as e:
    pytest.fail(f"Module imports are not available: {e}")

# Test data constants
TEMP_FILE_NAMING_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.tmp\."
CLEANUP_VERIFICATION_DELAY = 1.0  # seconds
CLEANUP_SUCCESS_RATE_TARGET = 1.0  # 100%

from unittest.mock import Mock, AsyncMock, MagicMock

def make_mock_method(
    method_name: str,
    is_async: bool = False,
    is_magic: bool = True,
    return_value: Optional[Any] = None,
    side_effects: Optional[List[Any]] = None
):


def make_magic_mock(
        is_async: bool = False,
        is_magic: bool = True,
        spec: Optional[Any] = None,
        method_with_return_value: Optional[Dict[str, Any]] = None
        ) -> Mock | AsyncMock | MagicMock:
    """
    Factory function to create a MagicMock instance with specified methods and return values.

    Args:
        spec (Optional[Any]): The specification for the mock object, if any.
        method_with_return_value (Optional[Dict[str, Any]]): A dictionary where keys are method names
            and values are the return values for those methods.

    Returns:
        MagicMock: A MagicMock instance with the specified methods and return values.
    
    
    """
    mock = MagicMock(spec=spec)

    if return_value is not None:
        if not isinstance(return_value, dict):
            raise TypeError("return_values must be a dictionary")
        default_to_success = AsyncMock(return_value=return_value)


    return mock

@pytest.fixture
def make_mock_ffmpeg(tmp_path):
    mock = MagicMock(spec=FFmpegWrapper)
    mock.convert_video = AsyncMock(return_value={
        "status": "success",
        "output_path": str(tmp_path / "converted.mp4")
    })
    defaults = AsyncMock(return_value={
        "status": "success",
        "output_path": str(Path(tempfile.TemporaryDirectory()) / "video.mp4"),
        "title": "Test Video",
        "download_id": str(uuid.uuid4()),
        "action": "downloaded",
        "url": "https://example.com/video",
        "info": {
            "title": "Test Video",
            "duration": 120,
            "uploader": "Test Channel",
            "upload_date": "20240101",
            "view_count": 1000,
            "formats": [{"format_id": "best", "ext": "mp4"}]
        },
        "duration": 120,
        "uploader": "Test Channel", 
        "upload_date": "20240101",
        "view_count": 1000,
        "formats": [{"format_id": "best", "ext": "mp4"}]
    })



    return mock

class TestCleanupCompletionRate:
    """Test cleanup completion rate criteria for temporary file management."""

    def test_ensure_docstring_quality(self):
        """
        Ensure that the docstring of the MediaProcessor class meets the standards set forth in `_example_docstring_format.md`.
        
        WHERE:
        - docstring: Triple-quoted string with summary, parameters, returns, and examples
        - MediaProcessor class: Video/audio download and conversion service with temporary file management
        - standards: Format requirements specified in `_example_docstring_format.md`
        """
        assert has_good_callable_metadata(MediaProcessor)

    @pytest.mark.asyncio
    async def test_download_and_convert_method_exists_and_is_callable(self, tmp_path):
        """
        GIVEN MediaProcessor class
        WHEN accessing download_and_convert method
        THEN method exists and is callable
        
        WHERE:
        - download_and_convert: Public method for media processing with cleanup
        - callable: Method can be invoked with proper parameters
        """
        processor = make_media_processor(default_output_dir=tmp_path)
        
        assert hasattr(processor, 'download_and_convert'), "MediaProcessor missing download_and_convert method"
        assert callable(processor.download_and_convert), "download_and_convert is not callable"
        assert asyncio.iscoroutinefunction(processor.download_and_convert), "download_and_convert is not async"

    @pytest.mark.asyncio
    async def test_get_capabilities_method_exists_and_returns_dict(self, tmp_path):
        """
        GIVEN MediaProcessor class
        WHEN calling get_capabilities method
        THEN method returns dictionary with capability information
        
        WHERE:
        - get_capabilities: Public method returning processor capabilities
        - dictionary: Return type containing capability flags and information
        """
        processor = make_media_processor(default_output_dir=tmp_path)
        
        capabilities = processor.get_capabilities()
        
        assert isinstance(capabilities, dict), f"get_capabilities returned {type(capabilities)}, expected dict"
        assert len(capabilities) > 0, "get_capabilities returned empty dictionary"

    @pytest.mark.asyncio
    async def test_download_and_convert_accepts_required_parameters(self, tmp_path):
        """
        GIVEN MediaProcessor instance
        WHEN calling download_and_convert with required parameters
        THEN method accepts url, output_format, and quality parameters
        
        WHERE:
        - required parameters: url (str), output_format (str), quality (str)
        - method signature: Parameters match expected types and names
        """
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        # This should not raise an exception
        try:
            result = await processor.download_and_convert(
                url="https://example.com/video",
                output_format="mp4", 
                quality="720p"
            )
            method_accepts_parameters = True
        except TypeError as e:
            method_accepts_parameters = False
            error_message = str(e)
        
        assert method_accepts_parameters, f"download_and_convert rejected required parameters: {error_message if 'error_message' in locals() else 'unknown error'}"

    @pytest.mark.asyncio  
    async def test_download_and_convert_returns_success_status_dict(self, tmp_path):
        """
        GIVEN successful download and convert operation
        WHEN download_and_convert completes successfully  
        THEN returns dictionary with status 'success'
        
        WHERE:
        - success status: Dictionary containing 'status': 'success' key-value pair
        - return type: Dict[str, Any] as specified in method annotation
        """
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert isinstance(result, dict), f"download_and_convert returned {type(result)}, expected dict"
        assert "status" in result, f"Result missing 'status' key, got keys: {list(result.keys())}"
        assert result["status"] == "success", f"Expected status 'success', got '{result['status']}'"

    @pytest.mark.asyncio
    async def test_download_and_convert_returns_error_status_on_failure(self, tmp_path):
        """
        GIVEN failed download operation
        WHEN download_and_convert encounters error
        THEN returns dictionary with status 'error'
        
        WHERE:
        - error status: Dictionary containing 'status': 'error' key-value pair
        - failure handling: Method handles exceptions and returns error status
        """
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(side_effect=Exception("Download failed"))
        
        mock_ffmpeg = MagicMock() 
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert isinstance(result, dict), f"download_and_convert returned {type(result)}, expected dict"
        assert "status" in result, f"Result missing 'status' key, got keys: {list(result.keys())}"
        assert result["status"] == "error", f"Expected status 'error', got '{result['status']}'"

    @pytest.mark.asyncio
    async def test_successful_operation_includes_output_path(self, tmp_path):
        """
        GIVEN successful download and convert operation
        WHEN download_and_convert completes successfully
        THEN result includes output_path key with file path
        
        WHERE:
        - output_path: String path to final converted file
        - successful operation: Both download and conversion complete without errors
        """
        output_file = tmp_path / "final_output.mp4"
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(output_file)})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert "output_path" in result, f"Result missing 'output_path' key, got keys: {list(result.keys())}"
        assert isinstance(result["output_path"], str), f"output_path is {type(result['output_path'])}, expected str"
        assert len(result["output_path"]) > 0, "output_path is empty string"

    @pytest.mark.asyncio
    async def test_error_result_includes_error_message(self, tmp_path):
        """
        GIVEN failed operation
        WHEN download_and_convert encounters error
        THEN result includes error key with descriptive message
        
        WHERE:
        - error message: String describing what went wrong
        - error key: Dictionary key containing human-readable error description
        """
        error_message = "Network connection failed"
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(side_effect=Exception(error_message))
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert "error" in result, f"Error result missing 'error' key, got keys: {list(result.keys())}"
        assert isinstance(result["error"], str), f"error value is {type(result['error'])}, expected str"
        assert len(result["error"]) > 0, "error message is empty string"

    @pytest.mark.asyncio
    async def test_ytdlp_wrapper_is_called_during_operation(self, tmp_path):
        """
        GIVEN MediaProcessor with mock ytdlp wrapper
        WHEN download_and_convert is called
        THEN ytdlp wrapper download_video method is invoked
        
        WHERE:
        - ytdlp wrapper: YtDlpWrapper instance handling video downloads
        - download_video method: Async method for downloading videos from URLs
        """
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert mock_ytdlp.download_video.called, "ytdlp.download_video was not called"
        assert mock_ytdlp.download_video.call_count == 1, f"ytdlp.download_video called {mock_ytdlp.download_video.call_count} times, expected 1"

    @pytest.mark.asyncio
    async def test_ffmpeg_wrapper_is_called_during_operation(self, tmp_path):
        """
        GIVEN MediaProcessor with mock ffmpeg wrapper
        WHEN download_and_convert is called
        THEN ffmpeg wrapper convert_video method is invoked
        
        WHERE:
        - ffmpeg wrapper: FFmpegWrapper instance handling video conversion
        - convert_video method: Async method for converting video formats
        """
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert mock_ffmpeg.convert_video.called, "ffmpeg.convert_video was not called"
        assert mock_ffmpeg.convert_video.call_count == 1, f"ffmpeg.convert_video called {mock_ffmpeg.convert_video.call_count} times, expected 1"

    @pytest.mark.asyncio
    async def test_url_parameter_is_passed_to_ytdlp_wrapper(self, tmp_path):
        """
        GIVEN MediaProcessor with mock ytdlp wrapper
        WHEN download_and_convert is called with specific URL
        THEN URL parameter is passed to ytdlp download_video method
        
        WHERE:
        - URL parameter: String URL passed to download_and_convert method
        - parameter passing: URL is forwarded to ytdlp wrapper without modification
        """
        test_url = "https://example.com/specific-video-123"
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        await processor.download_and_convert(
            url=test_url,
            output_format="mp4",
            quality="720p"
        )
        
        call_args = mock_ytdlp.download_video.call_args
        assert call_args is not None, "ytdlp.download_video was not called with any arguments"
        
        # Check if URL was passed as positional or keyword argument
        url_passed = False
        if call_args[0] and test_url in call_args[0]:  # Positional args
            url_passed = True
        elif call_args[1] and call_args[1].get('url') == test_url:  # Keyword args
            url_passed = True
        
        assert url_passed, f"URL '{test_url}' was not passed to ytdlp.download_video. Call args: {call_args}"

    @pytest.mark.asyncio
    async def test_output_format_parameter_is_used_in_conversion(self, tmp_path):
        """
        GIVEN MediaProcessor with mock ffmpeg wrapper
        WHEN download_and_convert is called with specific output_format
        THEN output_format parameter is used in ffmpeg conversion
        
        WHERE:
        - output_format parameter: String format specification (e.g., 'mp4', 'avi')
        - conversion usage: Format is passed to ffmpeg wrapper for conversion
        """
        test_format = "webm"
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.webm")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        await processor.download_and_convert(
            url="https://example.com/video",
            output_format=test_format,
            quality="720p"
        )
        
        call_args = mock_ffmpeg.convert_video.call_args
        assert call_args is not None, "ffmpeg.convert_video was not called with any arguments"
        
        # Check if format was passed as positional or keyword argument
        format_passed = False
        if call_args[0] and test_format in str(call_args[0]):  # Positional args
            format_passed = True
        elif call_args[1] and test_format in str(call_args[1].values()):  # Keyword args
            format_passed = True
        
        assert format_passed, f"Format '{test_format}' was not passed to ffmpeg.convert_video. Call args: {call_args}"

    @pytest.mark.asyncio
    async def test_quality_parameter_is_used_in_download(self, tmp_path):
        """
        GIVEN MediaProcessor with mock ytdlp wrapper
        WHEN download_and_convert is called with specific quality
        THEN quality parameter is used in ytdlp download
        
        WHERE:
        - quality parameter: String quality specification (e.g., '720p', '1080p')
        - download usage: Quality is passed to ytdlp wrapper for download
        """
        test_quality = "1080p"
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality=test_quality
        )
        
        call_args = mock_ytdlp.download_video.call_args
        assert call_args is not None, "ytdlp.download_video was not called with any arguments"
        
        # Check if quality was passed as positional or keyword argument
        quality_passed = False
        if call_args[0] and test_quality in str(call_args[0]):  # Positional args
            quality_passed = True
        elif call_args[1] and test_quality in str(call_args[1].values()):  # Keyword args
            quality_passed = True
        
        assert quality_passed, f"Quality '{test_quality}' was not passed to ytdlp.download_video. Call args: {call_args}"

    @pytest.mark.asyncio
    async def test_download_failure_stops_conversion_attempt(self, tmp_path):
        """
        GIVEN ytdlp download failure
        WHEN download_and_convert encounters download error
        THEN ffmpeg conversion is not attempted
        
        WHERE:
        - download failure: ytdlp.download_video raises exception or returns error status
        - conversion prevention: ffmpeg.convert_video is not called after download failure
        """
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(side_effect=Exception("Download failed"))
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert mock_ytdlp.download_video.called, "ytdlp.download_video should have been called"
        assert not mock_ffmpeg.convert_video.called, "ffmpeg.convert_video should not be called after download failure"
        assert result["status"] == "error", f"Expected error status after download failure, got '{result['status']}'"

    @pytest.mark.asyncio
    async def test_conversion_failure_returns_error_status(self, tmp_path):
        """
        GIVEN successful download but failed conversion
        WHEN download_and_convert encounters conversion error
        THEN returns error status with conversion failure details
        
        WHERE:
        - successful download: ytdlp.download_video completes successfully
        - conversion failure: ffmpeg.convert_video raises exception or returns error
        - error status: Method returns status 'error' despite successful download
        """
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "video.mp4")})
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(side_effect=Exception("Conversion failed"))
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert mock_ytdlp.download_video.called, "ytdlp.download_video should have been called"
        assert mock_ffmpeg.convert_video.called, "ffmpeg.convert_video should have been called"
        assert result["status"] == "error", f"Expected error status after conversion failure, got '{result['status']}'"

    def test_get_capabilities_includes_supported_operations(self, tmp_path):
        """
        GIVEN MediaProcessor instance
        WHEN get_capabilities is called
        THEN result includes supported_operations dictionary
        
        WHERE:
        - supported_operations: Dictionary containing operation capability flags
        - operation capabilities: Boolean flags for download, convert
        """
        mock_ytdlp = MagicMock()
        mock_ffmpeg = MagicMock()
        capabilities = ['download', 'convert']

        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )

        for capability in processor.get_capabilities().keys():
            assert capability in capabilities, f"Capabilities missing 'supported_operations' key, got keys: {list(capabilities.keys())}"

    def test_processor_has_default_output_dir_attribute(self, tmp_path):
        """
        GIVEN MediaProcessor instance created with default_output_dir
        WHEN accessing default_output_dir attribute
        THEN attribute exists and contains the specified directory path
        
        WHERE:
        - default_output_dir: Public attribute storing default output directory path
        - directory path: String path to directory for output files
        """
        processor = make_media_processor(default_output_dir=tmp_path)

        assert processor.default_output_dir == test_dir, f"default_output_dir is '{processor.default_output_dir}', expected '{test_dir}'"

    def test_processor_has_enable_logging_attribute(self, tmp_path):
        """
        GIVEN MediaProcessor instance created with enable_logging flag
        WHEN accessing enable_logging attribute
        THEN attribute exists and contains the specified boolean value
        
        WHERE:
        - enable_logging: Public attribute storing logging configuration flag
        - boolean value: True or False indicating if logging is enabled
        """
        processor = make_media_processor(
            default_output_dir=tmp_path,
            enable_logging=True
        )
        
        assert hasattr(processor, 'enable_logging'), "MediaProcessor missing enable_logging attribute"
        assert isinstance(processor.enable_logging, bool), f"enable_logging is {type(processor.enable_logging)}, expected bool"
        assert processor.enable_logging == True, f"enable_logging is {processor.enable_logging}, expected True"

    def test_processor_has_logger_attribute_when_logging_enabled(self, tmp_path):
        """
        GIVEN MediaProcessor instance with logging enabled
        WHEN accessing logger attribute
        THEN attribute exists and is not None
        
        WHERE:
        - logger: Public attribute storing logger instance for the processor
        - logging enabled: enable_logging=True was passed to constructor
        """
        processor = make_media_processor(
            default_output_dir=tmp_path,
            enable_logging=True
        )
        
        assert hasattr(processor, 'logger'), "MediaProcessor missing logger attribute"
        assert processor.logger is not None, "logger attribute is None when logging is enabled"

    def test_processor_has_ytdlp_attribute(self, tmp_path):
        """
        GIVEN MediaProcessor instance
        WHEN accessing ytdlp attribute
        THEN attribute exists and contains YtDlpWrapper instance
        
        WHERE:
        - ytdlp: Public attribute storing YtDlpWrapper instance for downloads
        - YtDlpWrapper: Wrapper class for yt-dlp functionality
        """
        mock_ytdlp = MagicMock()
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp
        )
        
        assert hasattr(processor, 'ytdlp'), "MediaProcessor missing ytdlp attribute"
        assert processor.ytdlp is mock_ytdlp, f"ytdlp attribute is {processor.ytdlp}, expected {mock_ytdlp}"

    def test_processor_has_ffmpeg_attribute(self, tmp_path):
        """
        GIVEN MediaProcessor instance
        WHEN accessing ffmpeg attribute
        THEN attribute exists and contains FFmpegWrapper instance
        
        WHERE:
        - ffmpeg: Public attribute storing FFmpegWrapper instance for conversion
        - FFmpegWrapper: Wrapper class for FFmpeg functionality
        """
        mock_ffmpeg = MagicMock()
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ffmpeg=mock_ffmpeg
        )
        
        assert hasattr(processor, 'ffmpeg'), "MediaProcessor missing ffmpeg attribute"
        assert processor.ffmpeg is mock_ffmpeg, f"ffmpeg attribute is {processor.ffmpeg}, expected {mock_ffmpeg}"

    @pytest.mark.asyncio
    async def test_successful_result_contains_title_field(self, tmp_path):
        """
        GIVEN successful download_and_convert operation
        WHEN result is returned
        THEN result contains title field with video title
        
        WHERE:
        - title field: String containing the title of the processed video
        - successful operation: download_and_convert returns status 'success'
        """
        video_title = "Test Video Title"
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={
            "status": "success", 
            "output_path": str(tmp_path / "video.mp4"),
            "title": video_title
        })
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert "title" in result, f"Result missing 'title' key, got keys: {list(result.keys())}"
        assert isinstance(result["title"], str), f"title is {type(result['title'])}, expected str"
        assert result["title"] == video_title, f"title is '{result['title']}', expected '{video_title}'"

    @pytest.mark.asyncio
    async def test_successful_result_contains_duration_field(self, tmp_path):
        """
        GIVEN successful download_and_convert operation
        WHEN result is returned
        THEN result contains duration field with video duration in seconds
        
        WHERE:
        - duration field: Float containing video duration in seconds
        - successful operation: download_and_convert returns status 'success'
        """
        video_duration = 120.5
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={
            "status": "success", 
            "output_path": str(tmp_path / "video.mp4"),
            "duration": video_duration
        })
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert "duration" in result, f"Result missing 'duration' key, got keys: {list(result.keys())}"
        assert isinstance(result["duration"], (int, float)), f"duration is {type(result['duration'])}, expected int or float"
        assert result["duration"] == video_duration, f"duration is {result['duration']}, expected {video_duration}"

    @pytest.mark.asyncio
    async def test_successful_result_contains_filesize_field(self, tmp_path):
        """
        GIVEN successful download_and_convert operation
        WHEN result is returned
        THEN result contains filesize field with file size in bytes
        
        WHERE:
        - filesize field: Integer containing file size in bytes
        - successful operation: download_and_convert returns status 'success'
        """
        file_size = 1048576  # 1MB in bytes
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={
            "status": "success", 
            "output_path": str(tmp_path / "video.mp4"),
            "filesize": file_size
        })
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="mp4",
            quality="720p"
        )
        
        assert "filesize" in result, f"Result missing 'filesize' key, got keys: {list(result.keys())}"
        assert isinstance(result["filesize"], int), f"filesize is {type(result['filesize'])}, expected int"
        assert result["filesize"] == file_size, f"filesize is {result['filesize']}, expected {file_size}"

    @pytest.mark.asyncio
    async def test_successful_result_contains_format_field(self, tmp_path):
        """
        GIVEN successful download_and_convert operation
        WHEN result is returned
        THEN result contains format field with downloaded format
        
        WHERE:
        - format field: String containing the format of the downloaded file
        - successful operation: download_and_convert returns status 'success'
        """
        download_format = "mp4"
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={
            "status": "success", 
            "output_path": str(tmp_path / "video.mp4"),
            "format": download_format
        })
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="webm",
            quality="720p"
        )
        
        assert "format" in result, f"Result missing 'format' key, got keys: {list(result.keys())}"
        assert isinstance(result["format"], str), f"format is {type(result['format'])}, expected str"
        assert result["format"] == download_format, f"format is '{result['format']}', expected '{download_format}'"

    @pytest.mark.asyncio
    async def test_successful_result_contains_converted_path_when_conversion_occurs(self, tmp_path):
        """
        GIVEN successful download and conversion to different format
        WHEN result is returned
        THEN result contains converted_path field with path to converted file
        
        WHERE:
        - converted_path field: String path to file after format conversion
        - conversion occurs: output_format differs from downloaded format
        """
        converted_path = str(tmp_path / "converted.webm")
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={
            "status": "success", 
            "output_path": str(tmp_path / "video.mp4"),
            "format": "mp4"
        })
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": converted_path})
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="webm",
            quality="720p"
        )
        
        assert "converted_path" in result, f"Result missing 'converted_path' key, got keys: {list(result.keys())}"
        assert isinstance(result["converted_path"], str), f"converted_path is {type(result['converted_path'])}, expected str"
        assert result["converted_path"] == converted_path, f"converted_path is '{result['converted_path']}', expected '{converted_path}'"

    @pytest.mark.asyncio
    async def test_successful_result_contains_conversion_result_when_conversion_occurs(self, tmp_path):
        """
        GIVEN successful download and conversion
        WHEN result is returned
        THEN result contains conversion_result field with conversion operation details
        
        WHERE:
        - conversion_result field: Dictionary containing conversion operation details
        - conversion operation: FFmpeg conversion process details and results
        """
        conversion_details = {
            "input_format": "mp4",
            "output_format": "webm", 
            "duration": 120.0,
            "bitrate": "1000k"
        }
        
        mock_ytdlp = MagicMock()
        mock_ytdlp.download_video = AsyncMock(return_value={
            "status": "success", 
            "output_path": str(tmp_path / "video.mp4"),
            "format": "mp4"
        })
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.convert_video = AsyncMock(return_value={
            "status": "success", 
            "output_path": str(tmp_path / "converted.webm"),
            "conversion_details": conversion_details
        })
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg
        )
        
        result = await processor.download_and_convert(
            url="https://example.com/video",
            output_format="webm",
            quality="720p"
        )
        
        assert "conversion_result" in result, f"Result missing 'conversion_result' key, got keys: {list(result.keys())}"
        assert isinstance(result["conversion_result"], dict), f"conversion_result is {type(result['conversion_result'])}, expected dict"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])