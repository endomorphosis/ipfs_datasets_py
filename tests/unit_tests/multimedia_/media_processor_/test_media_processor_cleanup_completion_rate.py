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
assert hasattr(MediaProcessor, 'download_and_convert')
assert hasattr(MediaProcessor, 'get_capabilities')

assert asyncio.iscoroutinefunction(MediaProcessor.download_and_convert)

# Function to extract instance attributes from __init__ method without instantiation
def get_instance_attributes_from_init(cls):
    """Extract instance attributes that will be set by __init__ method with their types."""
    import ast
    import inspect

    assert hasattr(cls, '__init__'), f"Class '{cls.__name__}' does not have an __init__ method defined."

    source = inspect.getsource(cls.__init__)
    tree = ast.parse(source)

    attributes = {}

    # Get type annotations from the class
    class_annotations = getattr(cls, '__annotations__', None)
    assert class_annotations is not None, f"Class '{cls.__name__}' does not have type annotations defined."

    # Walk through the AST to find self.attribute assignments
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    # ex: self.example = "value"
                    if isinstance(target.value, ast.Name) and target.value.id == 'self':
                        attr_name = target.attr
                        
                        # Try to get type from class annotations first
                        attr_type = class_annotations.get(attr_name, None)
                        
                        # If not found in class annotations, try to infer from assignment
                        if attr_type is None:
                            if isinstance(node.value, ast.Name):
                                # Simple assignment like self.attr = param
                                attr_type = "Any"
                            elif isinstance(node.value, ast.Call):
                                # Constructor call like self.attr = SomeClass()
                                if isinstance(node.value.func, ast.Name):
                                    attr_type = node.value.func.id
                                elif isinstance(node.value.func, ast.Attribute):
                                    attr_type = ast.unparse(node.value.func)
                                else:
                                    attr_type = "Any"
                            else:
                                attr_type = "Any"
                        
                        attributes[attr_name] = attr_type
    
    return attributes

# Check if the classes have their relevant public methods accessible
assert hasattr(YtDlpWrapper, 'download_video')
assert asyncio.iscoroutinefunction(YtDlpWrapper.download_video)

assert hasattr(FFmpegWrapper, 'convert_video')
assert asyncio.iscoroutinefunction(FFmpegWrapper.convert_video)

# Check instance attributes without instantiation
media_processor_attributes = get_instance_attributes_from_init(MediaProcessor)
expected_attributes = {
    'ytdlp_wrapper': 'YtDlpWrapper',
    'ffmpeg_wrapper': 'FFmpegWrapper', 
    'enable_logging': 'bool'
}

# Verify that MediaProcessor __init__ sets the expected instance attributes
for attr_name, expected_type in expected_attributes.items():
    assert attr_name in media_processor_attributes, f"MediaProcessor does not have instance attribute '{attr_name}'"
    actual_type = media_processor_attributes[attr_name]
    assert actual_type == expected_type, f"MediaProcessor instance attribute '{attr_name}' type mismatch: expected '{expected_type}', got '{actual_type}' instead."


# Check if the each method's signatures and annotations are correct
import inspect
sig = inspect.signature(MediaProcessor.download_and_convert)
annotations = sig.parameters
assert 'url' in annotations
assert 'output_format' in annotations  
assert 'quality' in annotations

# Check get_capabilities method
get_caps_sig = inspect.signature(MediaProcessor.get_capabilities)
# Method might be static/class method, so just check it exists

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


def create_mock_ytdlp(tmp_path, **kwargs):
    """
    Factory function to create mock YtDlpWrapper with configurable return values.
    
    Args:
        tmp_path: Temporary directory path for output files
        **kwargs: Override values for the download_video return value
            - status: success/error status (default: "success")
            - output_path: path to downloaded file (default: tmp_path / "video.mp4")
            - title: video title (default: "Test Video")
            - duration: video duration (default: 120)
            - filesize: file size in bytes (default: 1048576)
            - format: video format (default: "mp4")
            - side_effect: Exception to raise instead of returning value
    
    Returns:
        MagicMock: Configured mock YtDlpWrapper instance
    """
    mock = MagicMock()
    
    # Default return values
    default_return = {
        "status": "success",
        "output_path": str(tmp_path / "video.mp4"),
        "title": "Test Video",
        "duration": 420,
        "filesize": 6911,
        "format": "mp4"
    }
    if kwargs:
        # Add any additional keys provided in kwargs
        default_return.update(kwargs)
    
    # Handle side_effect for exception testing
    if "side_effect" in kwargs:
        mock.download_video = AsyncMock(side_effect=kwargs["side_effect"])
    else:
        mock.download_video = AsyncMock(return_value=default_return)
    
    return mock


def create_mock_ffmpeg(tmp_path, **kwargs):
    """
    Factory function to create mock FFmpegWrapper with configurable return values.
    
    Args:
        tmp_path: Temporary directory path for output files
        **kwargs: Override values for the convert_video return value
            - status: success/error status (default: "success")
            - output_path: path to converted file (default: tmp_path / "converted.mp4")
            - conversion_details: conversion operation details (default: None)
            - side_effect: Exception to raise instead of returning value
    
    Returns:
        MagicMock: Configured mock FFmpegWrapper instance
    """
    mock = MagicMock()
    
    # Default return values
    default_return = {
        "status": kwargs.get("status", "success"),
        "output_path": kwargs.get("output_path", str(tmp_path / "converted.mp4"))
    }
    
    # Add conversion_details if provided
    if "conversion_details" in kwargs:
        default_return["conversion_details"] = kwargs["conversion_details"]
    
    # Handle side_effect for exception testing
    if "side_effect" in kwargs:
        mock.convert_video = AsyncMock(side_effect=kwargs["side_effect"])
    else:
        mock.convert_video = AsyncMock(return_value=default_return)
    
    return mock


def create_mock_processor(tmp_path, ytdlp_kwargs=None, ffmpeg_kwargs=None, **processor_kwargs):
    """
    Factory function to create MediaProcessor with mock dependencies.
    
    Args:
        tmp_path: Temporary directory path for output files
        ytdlp_kwargs: Keyword arguments for ytdlp mock configuration
        ffmpeg_kwargs: Keyword arguments for ffmpeg mock configuration
        **processor_kwargs: Additional keyword arguments for make_media_processor
    
    Returns:
        MediaProcessor: Configured processor with mock dependencies
    """
    ytdlp_kwargs = ytdlp_kwargs or {}
    ffmpeg_kwargs = ffmpeg_kwargs or {}
    
    mock_ytdlp = create_mock_ytdlp(tmp_path, **ytdlp_kwargs)
    mock_ffmpeg = create_mock_ffmpeg(tmp_path, **ffmpeg_kwargs)
    
    return make_media_processor(
        default_output_dir=tmp_path,
        ytdlp=mock_ytdlp,
        ffmpeg=mock_ffmpeg,
        **processor_kwargs
    )

class TestCleanupCompletionRate:
    """Test cleanup completion rate criteria for temporary file management."""

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
        processor = create_mock_processor(tmp_path)
        
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
        processor = create_mock_processor(tmp_path)
        
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
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"side_effect": Exception("Download failed")}
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
        
        processor = create_mock_processor(
            tmp_path,
            ffmpeg_kwargs={"output_path": str(output_file)}
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
        
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"side_effect": Exception(error_message)}
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
        mock_ytdlp = create_mock_ytdlp(tmp_path)
        mock_ffmpeg = create_mock_ffmpeg(tmp_path)
        
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
        mock_ytdlp = create_mock_ytdlp(tmp_path)
        mock_ffmpeg = create_mock_ffmpeg(tmp_path)
        
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
        
        mock_ytdlp = create_mock_ytdlp(tmp_path)
        mock_ffmpeg = create_mock_ffmpeg(tmp_path)
        
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
        
        mock_ytdlp = create_mock_ytdlp(tmp_path)
        mock_ffmpeg = create_mock_ffmpeg(tmp_path, output_path=str(tmp_path / "converted.webm"))
        
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
        
        mock_ytdlp = create_mock_ytdlp(tmp_path)
        mock_ffmpeg = create_mock_ffmpeg(tmp_path)
        
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
        mock_ytdlp = create_mock_ytdlp(tmp_path, side_effect=Exception("Download failed"))
        mock_ffmpeg = create_mock_ffmpeg(tmp_path)
        
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
        mock_ytdlp = create_mock_ytdlp(tmp_path)
        mock_ffmpeg = create_mock_ffmpeg(tmp_path, side_effect=Exception("Conversion failed"))
        
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
        capabilities = ['download', 'convert']

        processor = create_mock_processor(tmp_path)

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

        assert processor.default_output_dir == tmp_path, f"default_output_dir is '{processor.default_output_dir}', expected '{tmp_path}'"

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
        mock_ytdlp = create_mock_ytdlp(tmp_path)
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp
        )

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
        mock_ffmpeg = create_mock_ffmpeg(tmp_path)
        
        processor = make_media_processor(
            default_output_dir=tmp_path,
            ffmpeg=mock_ffmpeg
        )

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
        
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"title": video_title}
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
        
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"duration": video_duration}
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
        
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"filesize": file_size}
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
        
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": download_format}
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
        
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": "mp4"},
            ffmpeg_kwargs={"output_path": converted_path}
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
        
        processor = create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": "mp4"},
            ffmpeg_kwargs={
                "output_path": str(tmp_path / "converted.webm"),
                "conversion_details": conversion_details
            }
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