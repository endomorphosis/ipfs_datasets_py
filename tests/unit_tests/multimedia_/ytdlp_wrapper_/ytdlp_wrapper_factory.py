#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test data factory for generating YtDlpWrapper instances and test data.

Provides methods to create valid baseline data, invalid variations, and edge cases
for comprehensive testing of the YtDlpWrapper class validation logic.
"""
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path
import tempfile
import uuid

from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper


class YtDlpWrapperTestDataFactory:
    """
    Test data factory for generating YtDlpWrapper instances and test data.
    
    Provides methods to create valid baseline data, invalid variations, and edge cases
    for comprehensive testing of the YtDlpWrapper class validation logic.
    
    Examples:
        >>> # Create a YtDlpWrapper instance for testing
        >>> wrapper = YtDlpWrapperTestDataFactory.create_wrapper_instance()
        >>> 
        >>> # Get valid video URLs for testing
        >>> urls = YtDlpWrapperTestDataFactory.create_valid_video_urls()
        >>> youtube_url = urls['youtube']  # "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        >>> 
        >>> # Get download options for different scenarios
        >>> options = YtDlpWrapperTestDataFactory.create_download_options()
        >>> audio_only = options['audio_only']  # {"audio_only": True, "audio_codec": "mp3", ...}
        >>> 
        >>> # Create wrapper with custom settings
        >>> custom_wrapper = YtDlpWrapperTestDataFactory.create_wrapper_instance(
        ...     default_quality="720p",
        ...     enable_logging=False
        ... )
    """

    @classmethod
    def create_valid_initialization_data(cls) -> Dict[str, Any]:
        """
        Create valid initialization parameters for YtDlpWrapper.
        
        Returns:
            Dict[str, Any]: Dictionary with valid initialization parameters.
                Keys:
                - 'default_output_dir': str - Directory for downloaded files (temp directory)
                - 'enable_logging': bool - Whether to enable logging (True)
                - 'default_quality': str - Default video quality setting ("best")
                
        Examples:
            >>> factory = YtDlpWrapperTestDataFactory()
            >>> init_data = factory.create_valid_initialization_data()
            >>> init_data['default_quality']
            'best'
        """
        return {
            "default_output_dir": tempfile.gettempdir(),
            "enable_logging": True,
            "default_quality": "best"
        }

    @classmethod
    def create_minimal_initialization_data(cls) -> Dict[str, Any]:
        """
        Create minimal initialization parameters for YtDlpWrapper.
        
        Returns:
            Dict[str, Any]: Dictionary with minimal initialization parameters.
                Keys:
                - 'default_output_dir': str - Basic output directory (temp directory)
                
        Examples:
            >>> factory = YtDlpWrapperTestDataFactory()
            >>> minimal_data = factory.create_minimal_initialization_data()
            >>> minimal_data['default_output_dir']
            '/tmp'
        """
        return {
            "default_output_dir": None,
            "enable_logging": False,
            "default_quality": "worst"
        }

    





    @classmethod
    def create_valid_video_urls(cls) -> Dict[str, str]:
        """
        Create dictionary of valid video URLs for testing.
        
        Returns:
            Dict[str, str]: Dictionary with valid video URLs.
                Keys:
                - 'youtube': str - Standard YouTube video URL
                - 'youtube_short': str - Short YouTube URL format (youtu.be)
                - 'vimeo': str - Vimeo video URL
                - 'soundcloud': str - SoundCloud track URL
                - 'twitch': str - Twitch video URL
                - 'dailymotion': str - Dailymotion video URL
        """
        return {
            "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube_short": "https://youtu.be/dQw4w9WgXcQ",
            "vimeo": "https://vimeo.com/123456789",
            "soundcloud": "https://soundcloud.com/artist/track-name",
            "twitch": "https://www.twitch.tv/videos/123456789",
            "dailymotion": "https://www.dailymotion.com/video/x123456"
        }

    @classmethod
    def create_invalid_video_urls(cls) -> Dict[str, str]:
        """
        Create dictionary of invalid video URLs for testing.
        
        Returns:
            Dict[str, str]: Dictionary with invalid video URLs.
                Keys:
                - 'empty': str - Empty string URL
                - 'none': None - None value instead of string
                - 'malformed': str - Malformed URL string ("not-a-url")
                - 'unsupported_protocol': str - URL with unsupported protocol (FTP)
                - 'invalid_domain': str - URL with non-existent domain
                - 'whitespace': str - URL with only whitespace characters
                - 'incomplete': str - Incomplete URL ("https://")
                - 'unsupported_site': str - URL from unsupported platform
        """
        return {
            "empty": "",
            "none": None,
            "malformed": "not-a-url",
            "unsupported_protocol": "ftp://example.com/video.mp4",
            "invalid_domain": "https://invalid-domain-that-does-not-exist.com/video",
            "whitespace": "   ",
            "incomplete": "https://",
            "unsupported_site": "https://example.com/video.mp4"
        }

    @classmethod
    def create_playlist_urls(cls) -> Dict[str, str]:
        """
        Create dictionary of playlist URLs for testing.
        
        Returns:
            Dict[str, str]: Dictionary with playlist URLs.
                Keys:
                - 'youtube_playlist': str - YouTube playlist URL with list parameter
                - 'soundcloud_set': str - SoundCloud playlist/set URL
                - 'vimeo_showcase': str - Vimeo showcase/album URL
                - 'youtube_channel': str - YouTube channel URL for bulk download
                - 'youtube_user': str - YouTube user page URL
        """
        return {
            "youtube_playlist": "https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6NumBgx-qF7kYnVQIgaqh",
            "soundcloud_set": "https://soundcloud.com/user/sets/playlist-name",
            "vimeo_showcase": "https://vimeo.com/showcase/123456",
            "youtube_channel": "https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw",
            "youtube_user": "https://www.youtube.com/user/username"
        }

    @classmethod
    def create_download_options(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create different download option combinations.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with download option sets.
                Keys:
                - 'basic': Dict - Basic download options
                  - 'quality': str - Quality setting ("best")
                - 'audio_only': Dict - Audio extraction options
                  - 'audio_only': bool - Extract audio only (True)
                  - 'audio_codec': str - Audio codec ("mp3")
                  - 'audio_quality': str - Audio quality ("192")
                - 'custom_quality': Dict - Custom quality options
                  - 'quality': str - Quality preference ("720p")
                  - 'format_selector': str - Format selector string
                - 'extract_info_only': Dict - Metadata extraction only
                  - 'extract_info_only': bool - Extract info without download (True)
                - 'with_subtitles': Dict - Download with subtitles
                  - 'writesubtitles': bool - Download subtitle files (True)
                  - 'writeautomaticsub': bool - Download auto-generated subtitles (True)
                - 'custom_output': Dict - Custom output path
                  - 'output_path': str - Custom output path template
        """
        return {
            "basic": {
                "quality": "best"
            },
            "audio_only": {
                "audio_only": True,
                "audio_codec": "mp3",
                "audio_quality": "192"
            },
            "custom_quality": {
                "quality": "720p",
                "format_selector": "best[height<=720]"
            },
            "extract_info_only": {
                "extract_info_only": True
            },
            "with_subtitles": {
                "writesubtitles": True,
                "writeautomaticsub": True
            },
            "custom_output": {
                "output_path": "/custom/path/%(title)s.%(ext)s"
            }
        }

    @classmethod
    def create_search_queries(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create search query test data.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with search query data.
                Keys:
                - 'basic_youtube': Dict - Basic YouTube search
                  - 'query': str - Search terms ("python tutorial")
                  - 'platform': str - Platform to search ("youtube")
                  - 'max_results': int - Maximum results to return (10)
                - 'soundcloud_music': Dict - SoundCloud music search
                - 'large_result_set': Dict - Search with many results (50)
                - 'single_result': Dict - Search returning only one result
        """
        return {
            "basic_youtube": {
                "query": "python tutorial",
                "platform": "youtube",
                "max_results": 10
            },
            "soundcloud_music": {
                "query": "ambient electronic music",
                "platform": "soundcloud",
                "max_results": 5
            },
            "large_result_set": {
                "query": "machine learning",
                "platform": "youtube",
                "max_results": 50
            },
            "single_result": {
                "query": "specific video title",
                "platform": "youtube",
                "max_results": 1
            }
        }

    @classmethod
    def create_expected_download_responses(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create expected download response structures.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with expected responses.
                Keys:
                - 'successful_download': Dict - Successful download response
                  - 'status': str - Success status ("success")
                  - 'action': str - Action performed ("downloaded")
                  - 'url': str - Original video URL
                  - 'output_path': str - Path to downloaded file
                  - 'download_id': str - Unique download identifier
                  - 'info': Dict - Download information
                - 'successful_info_extraction': Dict - Successful info extraction
                  - 'action': str - Action performed ("info_extracted")
                  - 'title': str - Video title
                  - 'duration': int - Video duration in seconds
                  - 'uploader': str - Channel/uploader name
                  - 'upload_date': str - Upload date (YYYYMMDD format)
                  - 'view_count': int - View count number
                  - 'formats': List - Available format list
                - 'playlist_download': Dict - Playlist download response
                  - 'action': str - Action performed ("playlist_downloaded")
                  - 'playlist_url': str - Original playlist URL
                  - 'downloaded_items': List - List of downloaded file paths
                  - 'failed_items': List - List of failed downloads
                  - 'total_downloaded': int - Count of successful downloads
                  - 'total_failed': int - Count of failed downloads
        """
        return {
            "successful_download": {
                "status": "success",
                "action": "downloaded",
                "url": "https://youtube.com/watch?v=example",
                "output_path": "/path/to/output/video_title.mp4",
                "download_id": str(uuid.uuid4()),
                "info": {}
            },
            "successful_info_extraction": {
                "status": "success",
                "action": "info_extracted",
                "title": "Example Video Title",
                "duration": 300,
                "uploader": "Example Channel",
                "upload_date": "20240101",
                "view_count": 1000000,
                "formats": []
            },
            "playlist_download": {
                "status": "success",
                "action": "playlist_downloaded",
                "playlist_url": "https://youtube.com/playlist?list=example",
                "download_id": str(uuid.uuid4()),
                "downloaded_items": [],
                "failed_items": [],
                "total_downloaded": 0,
                "total_failed": 0
            }
        }

    @classmethod
    def create_expected_error_responses(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create expected error response structures.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with expected error responses.
                Keys:
                - 'ytdlp_unavailable': Dict - YT-DLP not available error
                  - 'status': str - Error status ("error")
                  - 'error': str - Error description
                - 'invalid_url': Dict - Invalid URL format error
                  - 'status': str - Error status ("error")
                  - 'error': str - URL validation error message
                - 'download_error': Dict - General download failure
                  - 'status': str - Error status ("error")
                  - 'error': str - Download failure description
                - 'permission_error': Dict - File system permission error
                  - 'status': str - Error status ("error")
                  - 'error': str - Permission denied message
                  
        Examples:
            >>> factory = YtDlpWrapperTestDataFactory()
            >>> error_responses = factory.create_expected_error_responses()
            >>> error_responses['invalid_url']['status']
            'error'
        """
        return {
            "ytdlp_unavailable": {
                "status": "error",
                "error": "YT-DLP not available for download"
            },
            "invalid_url": {
                "status": "error",
                "error": "Invalid URL format"
            },
            "download_error": {
                "status": "error",
                "error": "Download error: Video unavailable"
            },
            "permission_error": {
                "status": "error",
                "error": "Permission denied for output directory"
            }
        }

    @classmethod
    def create_progress_callback_data(cls) -> Dict[str, Any]:
        """
        Create mock progress callback data.
        
        Returns:
            Dict[str, Any]: Dictionary with progress callback test data.
                Keys:
                - 'downloading': Dict - Active download progress
                  - 'status': str - Current status ("downloading")
                  - 'downloaded_bytes': int - Bytes downloaded so far
                  - 'total_bytes': int - Total file size in bytes
                  - '_percent_str': str - Percentage complete as string
                  - '_speed_str': str - Download speed display
                  - '_eta_str': str - Estimated time remaining
                - 'finished': Dict - Completed download status
                  - 'status': str - Status ("finished")
                  - 'downloaded_bytes': int - Total bytes downloaded
                  - 'total_bytes': int - Total file size
                  - 'filename': str - Path to downloaded file
                - 'error': Dict - Error state information
                  - 'status': str - Status ("error")
                  - 'error': str - Error message description
                  
        Examples:
            >>> factory = YtDlpWrapperTestDataFactory()
            >>> progress_data = factory.create_progress_callback_data()
            >>> progress_data['downloading']['status']
            'downloading'
        """
        return {
            "downloading": {
                "status": "downloading",
                "downloaded_bytes": 1024000,
                "total_bytes": 10240000,
                "_percent_str": "10.0%",
                "_speed_str": "1.2MiB/s",
                "_eta_str": "00:08"
            },
            "finished": {
                "status": "finished",
                "downloaded_bytes": 10240000,
                "total_bytes": 10240000,
                "filename": "/path/to/downloaded_file.mp4"
            },
            "error": {
                "status": "error",
                "error": "Network connection failed"
            }
        }

    @classmethod
    def create_batch_download_data(cls) -> Dict[str, List[str]]:
        """
        Create batch download URL lists for testing.
        
        Returns:
            Dict[str, List[str]]: Dictionary with URL lists for batch testing.
                Keys:
                - 'small_batch': List[str] - Small batch of 3 YouTube URLs
                - 'mixed_platforms': List[str] - URLs from different platforms (YouTube, Vimeo, SoundCloud)
                - 'large_batch': List[str] - Large batch of 20 YouTube URLs
                - 'single_url': List[str] - Single URL for minimal batch testing
                - 'empty_batch': List[str] - Empty list for edge case testing
        """
        return {
            "small_batch": [
                "https://youtube.com/watch?v=video1",
                "https://youtube.com/watch?v=video2",
                "https://youtube.com/watch?v=video3"
            ],
            "mixed_platforms": [
                "https://youtube.com/watch?v=video1",
                "https://vimeo.com/123456",
                "https://soundcloud.com/track"
            ],
            "large_batch": [f"https://youtube.com/watch?v=video{i}" for i in range(20)],
            "single_url": ["https://youtube.com/watch?v=single"],
            "empty_batch": []
        }

    @classmethod
    def create_wrapper_instance(cls, **overrides) -> YtDlpWrapper:
        """
        Create a YtDlpWrapper instance with optional overrides.
        
        Args:
            **overrides: Parameters to override in the initialization.
            
        Returns:
            YtDlpWrapper: Configured YtDlpWrapper instance.
        """
        data = cls.create_valid_initialization_data()
        data.update(overrides)
        return YtDlpWrapper(**data)

    @classmethod
    def create_minimal_wrapper_instance(cls, **overrides) -> YtDlpWrapper:
        """
        Create a minimal YtDlpWrapper instance with optional overrides.
        
        Args:
            **overrides: Parameters to override in the minimal initialization.
            
        Returns:
            YtDlpWrapper: Minimal YtDlpWrapper instance.
        """
        data = cls.create_minimal_initialization_data()
        data.update(overrides)
        return YtDlpWrapper(**data)

    @classmethod
    def create_mock_progress_callback(cls) -> Callable:
        """
        Create a mock progress callback function for testing.
        
        Returns:
            Callable: Mock progress callback function.
        """
        def mock_callback(download_id: str, progress_data: Dict[str, Any]):
            """Mock progress callback that stores call data."""
            if not hasattr(mock_callback, 'calls'):
                mock_callback.calls = []
            mock_callback.calls.append({
                'download_id': download_id,
                'progress_data': progress_data
            })
        return mock_callback

    @classmethod
    def create_download_status_data(cls) -> Dict[str, Dict[str, Any]]:
        """
        Create download status tracking data for testing.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary with download status data.
                Keys:
                - 'active_download': Dict - Currently downloading item
                  - 'url': str - Video URL being downloaded
                  - 'status': str - Current status ("downloading")
                  - 'start_time': float - Unix timestamp when download started
                  - 'output_dir': str - Directory for downloaded files
                - 'completed_download': Dict - Successfully completed download
                  - 'url': str - Downloaded video URL
                  - 'status': str - Status ("completed")
                  - 'start_time': float - Start timestamp
                  - 'end_time': float - Completion timestamp
                  - 'output_dir': str - Output directory
                  - 'result': Dict - Download result information
                - 'failed_download': Dict - Failed download attempt
                  - 'url': str - Failed video URL
                  - 'status': str - Status ("failed")
                  - 'start_time': float - Start timestamp
                  - 'end_time': float - Failure timestamp
                  - 'output_dir': str - Target directory
                  - 'error': str - Error message
                  
        Examples:
            >>> factory = YtDlpWrapperTestDataFactory()
            >>> status_data = factory.create_download_status_data()
            >>> status_data['active_download']['status']
            'downloading'
        """
        return {
            "active_download": {
                "url": "https://youtube.com/watch?v=example",
                "status": "downloading",
                "start_time": 1234567890.0,
                "output_dir": "/tmp/downloads"
            },
            "completed_download": {
                "url": "https://youtube.com/watch?v=example",
                "status": "completed",
                "start_time": 1234567890.0,
                "end_time": 1234567950.0,
                "output_dir": "/tmp/downloads",
                "result": {"status": "success"}
            },
            "failed_download": {
                "url": "https://youtube.com/watch?v=example",
                "status": "failed",
                "start_time": 1234567890.0,
                "end_time": 1234567920.0,
                "output_dir": "/tmp/downloads",
                "error": "Download failed"
            }
        }
