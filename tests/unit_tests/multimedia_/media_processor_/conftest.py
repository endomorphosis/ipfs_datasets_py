#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pytest fixtures for MediaProcessor tests.

Provides reusable fixtures for testing MediaProcessor functionality including
mock dependencies, test data, and temporary directories.
"""

import pytest
import tempfile
import uuid
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
from typing import Dict, Any

from ipfs_datasets_py.multimedia.media_processor import make_media_processor


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


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
def mock_processor(temp_dir, mock_ytdlp, mock_ffmpeg):
    """Create a MediaProcessor with mock dependencies."""
    return make_media_processor(
        default_output_dir=temp_dir,
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
    def create_mock_ytdlp(temp_dir, **kwargs):
        """
        Create a mock YtDlpWrapper with configurable return values.
        
        Args:
            temp_dir: Temporary directory path for output files
            **kwargs: Override values for the download_video return value
        
        Returns:
            MagicMock: Configured mock YtDlpWrapper instance
        """
        mock = MagicMock()
        
        default_return = {
            "status": "success",
            "output_path": str(temp_dir / "video.mp4"),
            "title": "Test Video",
            "duration": 420,
            "filesize": 6911,
            "format": "mp4"
        }
        
        if kwargs:
            default_return.update(kwargs)
        
        if "side_effect" in kwargs:
            mock.download_video = AsyncMock(side_effect=kwargs["side_effect"])
        else:
            mock.download_video = AsyncMock(return_value=default_return)
        
        return mock

    @staticmethod
    def create_mock_ffmpeg(temp_dir, **kwargs):
        """
        Create a mock FFmpegWrapper with configurable return values.
        
        Args:
            temp_dir: Temporary directory path for output files
            **kwargs: Override values for the convert_video return value
        
        Returns:
            MagicMock: Configured mock FFmpegWrapper instance
        """
        mock = MagicMock()
        
        default_return = {
            "status": kwargs.get("status", "success"),
            "output_path": kwargs.get("output_path", str(temp_dir / "converted.mp4"))
        }
        
        if "conversion_details" in kwargs:
            default_return["conversion_details"] = kwargs["conversion_details"]
        
        if "side_effect" in kwargs:
            mock.convert_video = AsyncMock(side_effect=kwargs["side_effect"])
        else:
            mock.convert_video = AsyncMock(return_value=default_return)
        
        return mock

    @staticmethod
    def create_mock_processor(temp_dir, ytdlp_kwargs=None, ffmpeg_kwargs=None, **processor_kwargs):
        """
        Create a MediaProcessor with mock dependencies.
        
        Args:
            temp_dir: Temporary directory path for output files
            ytdlp_kwargs: Keyword arguments for ytdlp mock configuration
            ffmpeg_kwargs: Keyword arguments for ffmpeg mock configuration
            **processor_kwargs: Additional keyword arguments for make_media_processor
        
        Returns:
            MediaProcessor: Configured processor with mock dependencies
        """
        ytdlp_kwargs = ytdlp_kwargs or {}
        ffmpeg_kwargs = ffmpeg_kwargs or {}
        
        mock_ytdlp = MockFactory.create_mock_ytdlp(temp_dir, **ytdlp_kwargs)
        mock_ffmpeg = MockFactory.create_mock_ffmpeg(temp_dir, **ffmpeg_kwargs)
        
        return make_media_processor(
            default_output_dir=temp_dir,
            ytdlp=mock_ytdlp,
            ffmpeg=mock_ffmpeg,
            **processor_kwargs
        )


@pytest.fixture
def mock_factory():
    """Provide the MockFactory class for creating custom mocks."""
    return MockFactory
