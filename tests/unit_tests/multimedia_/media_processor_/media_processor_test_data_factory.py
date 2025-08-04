from unittest.mock import MagicMock, AsyncMock


# Import the MediaProcessor class and its class dependencies
from ipfs_datasets_py.multimedia.media_processor import make_media_processor
from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper


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
        "status": kwargs.get("status", "success"),
        "output_path": kwargs.get("output_path", str(tmp_path / "video.mp4")),
        "title": kwargs.get("title", "Test Video"),
        "duration": kwargs.get("duration", 120),
        "filesize": kwargs.get("filesize", 1048576),
        "format": kwargs.get("format", "mp4")
    }
    
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