#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pytest fixtures for MediaProcessor tests.

Provides reusable fixtures for testing MediaProcessor functionality including
mock dependencies, test data, and temporary directories.
"""

import pytest
import uuid
import socket
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from typing import Dict, Any

from ipfs_datasets_py.multimedia.media_processor import make_media_processor, MediaProcessor


class _TestImplementationDetailError(Exception):
    """
    Exception raised when a test is testing implementation details instead of behavior.
    
    This error should be raised when a test focuses on internal implementation
    specifics rather than observable behavior or public API contracts.
    """
    pass


@pytest.fixture
def mock_ytdlp():
    """Create a mock YtDlpWrapper with default successful responses."""
    mock = MagicMock()
    mock.download_video = AsyncMock(return_value={
        "status": "success",
        "output_path": "/tmp/video.mp4",
        "title": "Test Video",
        "duration": 420,
        "filesize": 6911,
        "format": "mp4"
    })
    return mock


@pytest.fixture
def mock_ffmpeg():
    """Create a mock FFmpegWrapper with default successful responses."""
    mock = MagicMock()
    mock.convert_video = AsyncMock(return_value={
        "status": "success",
        "output_path": "/tmp/converted.mp4"
    })
    return mock


@pytest.fixture
def mock_processor(tmp_path, mock_ytdlp, mock_ffmpeg):
    """Create a MediaProcessor with mock dependencies."""
    return make_media_processor(
        default_output_dir=tmp_path,
        ytdlp=mock_ytdlp,
        ffmpeg=mock_ffmpeg
    )


@pytest.fixture
def test_url():
    """Provide a test URL for video processing."""
    return "https://example.com/video"


@pytest.fixture
def test_video_metadata():
    """Provide test video metadata."""
    return {
        "title": "Test Video Title",
        "duration": 120.5,
        "filesize": 1048576,
        "format": "mp4"
    }


@pytest.fixture
def mock_ytdlp_with_metadata(test_video_metadata):
    """Create a mock YtDlpWrapper that returns specific metadata."""
    mock = MagicMock()
    mock.download_video = AsyncMock(return_value={
        "status": "success",
        "output_path": "/tmp/video.mp4",
        **test_video_metadata
    })
    return mock


@pytest.fixture
def mock_ytdlp_failure():
    """Create a mock YtDlpWrapper that simulates download failure."""
    mock = MagicMock()
    mock.download_video = AsyncMock(side_effect=Exception("Download failed"))
    return mock


@pytest.fixture
def mock_ffmpeg_failure():
    """Create a mock FFmpegWrapper that simulates conversion failure."""
    mock = MagicMock()
    mock.convert_video = AsyncMock(side_effect=Exception("Conversion failed"))
    return mock


@pytest.fixture
def conversion_details():
    """Provide test conversion details."""
    return {
        "input_format": "mp4",
        "output_format": "webm",
        "duration": 120.0,
        "bitrate": "1000k"
    }


@pytest.fixture
def mock_ffmpeg_with_details(conversion_details):
    """Create a mock FFmpegWrapper that returns conversion details."""
    mock = MagicMock()
    mock.convert_video = AsyncMock(return_value={
        "status": "success",
        "output_path": "/tmp/converted.webm",
        "conversion_details": conversion_details
    })
    return mock


class MockFactory:
    """Factory for creating mock objects with custom configurations."""
    
    @staticmethod
    def create_mock_ytdlp(tmp_path, **kwargs):
        """
        Create a mock YtDlpWrapper with configurable return values.
        
        Args:
            tmp_path: Temporary directory path for output files
            **kwargs: Override values for the download_video return value
        
        Returns:
            MagicMock: Configured mock YtDlpWrapper instance
        """
        mock = MagicMock()
        
        # Handle None tmp_path case
        if tmp_path is None:
            base_path = "/tmp"
        else:
            base_path = str(tmp_path)
        
        # If format is specified and output_path is not, make them match
        format_ext = kwargs.get("format", "mp4")
        if "output_path" not in kwargs:
            output_path = f"{base_path}/video.{format_ext}"
        else:
            output_path = kwargs["output_path"]
        
        default_return = {
            "status": "success",
            "output_path": output_path,
            "title": "Test Video",
            "duration": 420,
            "filesize": 6911,
            "format": format_ext
        }
        
        if kwargs:
            default_return.update(kwargs)
        
        if "side_effect" in kwargs:
            mock.download_video = AsyncMock(side_effect=kwargs["side_effect"])
        else:
            mock.download_video = AsyncMock(return_value=default_return)
        
        return mock

    @staticmethod
    def create_mock_ffmpeg(tmp_path, **kwargs):
        """
        Create a mock FFmpegWrapper with configurable return values.
        
        Args:
            tmp_path: Temporary directory path for output files
            **kwargs: Override values for the convert_video return value
        
        Returns:
            MagicMock: Configured mock FFmpegWrapper instance
        """
        mock = MagicMock()
        
        # Handle None tmp_path case
        if tmp_path is None:
            base_path = "/tmp"
        else:
            base_path = str(tmp_path)
        
        default_return = {
            "status": kwargs.get("status", "success"),
            "output_path": kwargs.get("output_path", f"{base_path}/converted.mp4")
        }
        
        if "conversion_details" in kwargs:
            default_return["conversion_details"] = kwargs["conversion_details"]
        
        if "side_effect" in kwargs:
            mock.convert_video = AsyncMock(side_effect=kwargs["side_effect"])
        else:
            mock.convert_video = AsyncMock(return_value=default_return)
        
        return mock

    @staticmethod
    def create_mock_processor(tmp_path, ytdlp_kwargs=None, ffmpeg_kwargs=None, **processor_kwargs):
        """
        Create a MediaProcessor with mock dependencies.
        
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
        
        mock_ytdlp = MockFactory.create_mock_ytdlp(tmp_path, **ytdlp_kwargs)
        mock_ffmpeg = MockFactory.create_mock_ffmpeg(tmp_path, **ffmpeg_kwargs)
        
        return make_media_processor(
            default_output_dir=tmp_path,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg,
            **processor_kwargs
        )


@pytest.fixture
def mock_factory():
    """Provide the MockFactory class for creating custom mocks."""
    return MockFactory


# General test data fixtures
@pytest.fixture
def test_video_title():
    """Provide a test video title."""
    return "Test Video Title"


@pytest.fixture
def test_video_duration():
    """Provide a test video duration in seconds."""
    return 120.5


@pytest.fixture
def test_file_size():
    """Provide a test file size in bytes (1MB)."""
    return 1048576


@pytest.fixture
def test_download_format():
    """Provide a test video download format."""
    return "mp4"


@pytest.fixture
def test_error_message():
    """Provide a test error message."""
    return "Network connection failed"


@pytest.fixture
def test_converted_path(tmp_path):
    """Provide a test converted file path."""
    return str(tmp_path / "converted.webm")


@pytest.fixture
def test_expected_capabilities():
    """Provide expected MediaProcessor capabilities."""
    return ['download', 'convert']


# General processor fixtures
@pytest.fixture
def default_processor(tmp_path):
    """Create a MediaProcessor with default configuration and mock dependencies."""
    return MockFactory.create_mock_processor(tmp_path)


@pytest.fixture
def default_processor_with_logging(tmp_path):
    """Create a MediaProcessor with logging enabled and mock dependencies."""
    return MockFactory.create_mock_processor(
        tmp_path,
        enable_logging=True
    )


@pytest.fixture
def successful_processor(tmp_path):
    """Create a processor that returns successful results."""
    output_file = tmp_path / "final_output.mp4"
    return MockFactory.create_mock_processor(
        tmp_path,
        ffmpeg_kwargs={"output_path": str(output_file)}
    )


@pytest.fixture
def url_aware_processor(tmp_path):
    """Create a processor that returns different results based on URL."""
    def create_url_specific_response(url):
        # Extract video ID from URL to create unique responses
        if "v=" in url:
            video_id = url.split("v=")[1].split("&")[0]
            return {
                "status": "success",
                "output_path": str(tmp_path / f"video_{video_id}.mp4"),
                "title": f"Test Video {video_id}",
                "duration": hash(video_id) % 1000 + 100,  # Unique duration based on video_id
                "filesize": hash(video_id) % 50000 + 10000,  # Unique filesize based on video_id
                "format": "mp4",
                "converted_path": None,
                "conversion_result": None
            }
        else:
            # Default response for non-YouTube URLs
            return {
                "status": "success",
                "output_path": str(tmp_path / "video.mp4"),
                "title": "Test Video",
                "duration": 420,
                "filesize": 6911,
                "format": "mp4",
                "converted_path": None,
                "conversion_result": None
            }
    
    # Create YtDLP mock with URL-specific side effect
    mock_ytdlp = MagicMock()
    mock_ytdlp.download_video = AsyncMock(side_effect=lambda url, **kwargs: create_url_specific_response(url))
    
    # Create FFmpeg mock
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.convert_video = AsyncMock(return_value={"status": "success", "output_path": str(tmp_path / "converted.mp4")})
    
    # Create MediaProcessor with the URL-aware mocks
    processor = MediaProcessor(ytdlp=mock_ytdlp, ffmpeg=mock_ffmpeg, default_output_dir=str(tmp_path))
    return processor


@pytest.fixture
def download_failure_processor(tmp_path, test_error_message):
    """Create a processor that fails during download phase."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"side_effect": Exception(test_error_message)}
    )


@pytest.fixture
def download_failure_processor_alt(tmp_path):
    """Create an alternative processor that fails during download phase."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"side_effect": Exception("Download failed")}
    )


@pytest.fixture
def conversion_failure_processor(tmp_path):
    """Create a processor that succeeds download but fails conversion."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={},
        ffmpeg_kwargs={"side_effect": Exception("Conversion failed")}
    )


# Specialized processor fixtures with specific metadata
@pytest.fixture
def processor_with_title(tmp_path, test_video_title):
    """Create a processor configured to return specific video title."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"title": test_video_title}
    )


@pytest.fixture
def processor_with_duration(tmp_path, test_video_duration):
    """Create a processor configured to return specific video duration."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"duration": test_video_duration}
    )


@pytest.fixture
def processor_with_filesize(tmp_path, test_file_size):
    """Create a processor configured to return specific file size."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"filesize": test_file_size}
    )


@pytest.fixture
def processor_with_format(tmp_path, test_download_format):
    """Create a processor configured to return specific download format."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"format": test_download_format}
    )


@pytest.fixture
def conversion_processor(tmp_path, test_download_format):
    """Create a processor set up for format conversion testing."""
    # Set up ytdlp to return a video.mp4 file, and configure conversion to webm
    # The converted path will be video.webm (based on downloaded file name)
    downloaded_path = tmp_path / "video.mp4"
    converted_path = tmp_path / "video.webm" 
    
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={
            "format": test_download_format,
            "output_path": str(downloaded_path)
        },
        ffmpeg_kwargs={"output_path": str(converted_path)}
    )


@pytest.fixture
def conversion_processor_with_details(tmp_path, conversion_details, test_converted_path):
    """Create a processor set up for conversion with detailed conversion result."""
    return MockFactory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"format": "mp4"},
        ffmpeg_kwargs={
            "output_path": test_converted_path,
            "conversion_details": conversion_details
        }
    )


@pytest.fixture
def processor_with_mock_ytdlp(tmp_path):
    """Create a processor with specific ytdlp mock for testing."""
    mock_ytdlp = MockFactory.create_mock_ytdlp(tmp_path)
    processor = make_media_processor(
        default_output_dir=tmp_path,
        ytdlp=mock_ytdlp
    )
    return processor, mock_ytdlp


@pytest.fixture
def processor_with_mock_ffmpeg(tmp_path):
    """Create a processor with specific ffmpeg mock for testing."""
    mock_ffmpeg = MockFactory.create_mock_ffmpeg(tmp_path)
    processor = make_media_processor(
        default_output_dir=tmp_path,
        ffmpeg=mock_ffmpeg
    )
    return processor, mock_ffmpeg


@pytest.fixture 
def mock_capabilities_processor(tmp_path):
    """Create a processor for testing get_capabilities."""
    return MockFactory.create_mock_processor(tmp_path)


# Network error recovery fixtures
@pytest.fixture
def recoverable_http_errors():
    """HTTP status codes that should be classified as recoverable."""
    return [429, 500, 501, 502, 503, 504, 505, 507, 508, 509, 510, 511]


@pytest.fixture
def non_recoverable_http_errors():
    """HTTP status codes that should be classified as non-recoverable."""
    return [401, 403, 404, 410, 451]


@pytest.fixture
def recoverable_socket_errors():
    """Socket error types that should be classified as recoverable."""
    return ["timeout", "connection_reset", "connection_refused"]


@pytest.fixture
def non_recoverable_errors():
    """Error types that should be classified as non-recoverable."""
    return ["certificate_error", "ssl_error", "dns_failure"]


@pytest.fixture
def expected_retry_delays():
    """Expected exponential backoff delays in seconds."""
    return [1.0, 2.0, 4.0]


@pytest.fixture
def max_retry_attempts():
    """Maximum number of retry attempts before giving up."""
    return 3


@pytest.fixture
def recovery_rate_test_data():
    """Test data for recovery rate calculations."""
    return {
        "total_errors": 100,
        "successful_recoveries": 80,
        "expected_rate": 0.80,
        "minimum_threshold": 0.80
    }


# Conversion decision accuracy fixtures
@pytest.fixture
def error_processor(mock_factory, tmp_path):
    """Create a processor that fails with an error."""
    return mock_factory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"side_effect": Exception("Invalid URL")}
    )


@pytest.fixture
def same_format_processor(mock_factory, tmp_path):
    """Create a processor for testing same format conversions."""
    same_format = "mp4"
    return mock_factory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={"format": same_format}
    ), same_format


@pytest.fixture
def different_format_processor(mock_factory, tmp_path):
    """Create a processor for testing different format conversions."""
    input_format = "avi"
    output_format = "mp4"
    processor = mock_factory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={
            "format": input_format,
            "output_path": str(tmp_path / f"video.{input_format}")
        },
        ffmpeg_kwargs={"output_path": str(tmp_path / f"converted.{output_format}")}
    )
    return processor, input_format, output_format


@pytest.fixture
def equivalent_format_processor(mock_factory, tmp_path):
    """Create a processor for testing equivalent format conversions."""
    input_format = "m4v"
    output_format = "mp4"
    # For equivalent formats, mock the downloaded file to have the output format extension
    # so no conversion is triggered
    processor = mock_factory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={
            "format": input_format,
            "output_path": str(tmp_path / f"video.{output_format}")  # Use output format extension
        }
    )
    return processor, input_format, output_format


@pytest.fixture
def unknown_format_processor(mock_factory, tmp_path):
    """Create a processor for testing unknown format handling."""
    unknown_format = "xyz"
    standard_format = "mp4"
    processor = mock_factory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={
            "format": unknown_format,
            "output_path": str(tmp_path / f"video.{unknown_format}")
        },
        ffmpeg_kwargs={"output_path": str(tmp_path / f"converted.{standard_format}")}
    )
    return processor, unknown_format, standard_format


@pytest.fixture
def concurrent_processors(mock_factory, tmp_path):
    """Create multiple processors for concurrent testing."""
    count = 10  # Reduced from CONCURRENT_DECISION_COUNT for performance
    return [mock_factory.create_mock_processor(tmp_path) for _ in range(count)]


@pytest.fixture
def load_test_processor(mock_factory, tmp_path):
    """Create a processor for sustained load testing."""
    return mock_factory.create_mock_processor(tmp_path)


@pytest.fixture
def conversion_accuracy_processor(mock_factory, tmp_path):
    """Create a processor configured for accuracy testing."""
    return mock_factory.create_mock_processor(
        tmp_path,
        ytdlp_kwargs={
            "format": "avi",
            "output_path": str(tmp_path / "video.avi")
        },
        ffmpeg_kwargs={"output_path": str(tmp_path / "converted.mp4")}
    )


@pytest.fixture
def sample_size():
    """Provide a standard sample size for performance testing."""
    return 10  # Reduced for test performance


@pytest.fixture
def mock_http_error_response():
    """Create a mock HTTP error response."""
    def _create_response(status_code: int, error_message: str = None):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.text = error_message or f"HTTP {status_code} Error"
        return mock_response
    return _create_response


@pytest.fixture
def mock_socket_error():
    """Create mock socket errors."""
    def _create_socket_error(error_type: str):
        if error_type == "timeout":
            return socket.timeout("Connection timed out")
        elif error_type == "connection_reset":
            return ConnectionResetError("Connection reset by peer")
        elif error_type == "connection_refused":
            return ConnectionRefusedError("Connection refused")
        else:
            return socket.error(f"Socket error: {error_type}")
    return _create_socket_error


@pytest.fixture
def mock_processor_with_retry_tracking(tmp_path):
    """Create a processor that tracks retry attempts and delays."""
    mock_ytdlp = MagicMock()
    mock_ffmpeg = MagicMock()
    
    # Track retry attempts
    mock_ytdlp.retry_attempts = []
    mock_ytdlp.retry_delays = []
    
    processor = make_media_processor(
        default_output_dir=tmp_path,
        ytdlp=mock_ytdlp,
        ffmpeg=mock_ffmpeg
    )
    
    return processor, mock_ytdlp


@pytest.fixture
def mock_processor_with_error_classification(tmp_path):
    """Create a processor that provides error classification through download_and_convert results."""
    mock_ytdlp = MagicMock()
    mock_ffmpeg = MagicMock()
    
    processor = make_media_processor(
        default_output_dir=tmp_path,
        ytdlp=mock_ytdlp,
        ffmpeg=mock_ffmpeg
    )
    
    return processor


@pytest.fixture
def mock_processor_with_recovery_success(tmp_path):
    """Create a processor that succeeds after initial errors."""
    mock_ytdlp = MagicMock()
    
    # First call fails, second succeeds
    mock_ytdlp.download_video = AsyncMock(side_effect=[
        Exception("HTTP 500 Internal Server Error"),
        {
            "status": "success",
            "output_path": str(tmp_path / "recovered_video.mp4"),
            "title": "Recovered Video",
            "duration": 120,
            "filesize": 1048576,
            "format": "mp4"
        }
    ])
    
    return MockFactory.create_mock_processor(tmp_path, ytdlp_kwargs={})


@pytest.fixture
def mock_processor_with_recovery_failure(tmp_path, max_retry_attempts):
    """Create a processor that fails all retry attempts."""
    mock_ytdlp = MagicMock()
    
    # All attempts fail
    error_responses = [Exception("HTTP 500 Internal Server Error")] * (max_retry_attempts + 1)
    mock_ytdlp.download_video = AsyncMock(side_effect=error_responses)
    
    return MockFactory.create_mock_processor(tmp_path, ytdlp_kwargs={})


@pytest.fixture
def mock_processor_with_http_error_recovery(tmp_path):
    """Create a processor that simulates HTTP error recovery scenarios."""
    mock_ytdlp = MagicMock()
    
    # First call returns error status, subsequent calls succeed
    mock_ytdlp.download_video = AsyncMock(return_value={
        "status": "error",
        "error": "HTTP 429 Too Many Requests"
    })
    
    mock_ffmpeg = MagicMock()
    mock_ffmpeg.convert_video = AsyncMock(return_value={
        "status": "success",
        "output_path": str(tmp_path / "converted.mp4")
    })
    
    return make_media_processor(
        default_output_dir=tmp_path,
        ytdlp=mock_ytdlp,
        ffmpeg=mock_ffmpeg
    )


@pytest.fixture
def mock_processor_with_permanent_error(tmp_path):
    """Create a processor that returns permanent errors (non-recoverable)."""
    mock_ytdlp = MagicMock()
    
    # Always returns error status for non-recoverable errors
    mock_ytdlp.download_video = AsyncMock(return_value={
        "status": "error", 
        "error": "HTTP 404 Not Found"
    })
    
    return MockFactory.create_mock_processor(tmp_path, ytdlp_kwargs={})


@pytest.fixture
def mock_processor_with_exponential_backoff(tmp_path, expected_retry_delays):
    """Create a processor that can be tested for exponential backoff through download_and_convert."""
    processor = MockFactory.create_mock_processor(tmp_path)
    
    return processor


@pytest.fixture  
def mock_processor_with_recovery_statistics(tmp_path, recovery_rate_test_data):
    """Create a processor that provides recovery rate statistics through get_capabilities."""
    processor = MockFactory.create_mock_processor(tmp_path)
    
    return processor
