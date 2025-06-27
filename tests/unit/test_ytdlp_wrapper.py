"""
Unit tests for the YT-DLP wrapper library.

This test suite covers all major functionality of the YtDlpWrapper class
including video downloads, playlist handling, info extraction, search,
and batch operations.
"""

import asyncio
import json
import pytest
import tempfile
import unittest.mock
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

# Import the modules under test
from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper, YTDLP_AVAILABLE
from ipfs_datasets_py.multimedia import HAVE_YTDLP


class TestYtDlpWrapper:
    """Test suite for YtDlpWrapper class."""
    
    @pytest.fixture
    def wrapper(self):
        """Create a YtDlpWrapper instance for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield YtDlpWrapper(
                default_output_dir=temp_dir,
                enable_logging=True,
                default_quality="best"
            )
    
    @pytest.fixture
    def mock_ytdlp_success(self):
        """Mock successful yt-dlp operations."""
        mock_info = {
            "id": "test_video_id",
            "title": "Test Video Title",
            "uploader": "Test Channel",
            "duration": 300,
            "view_count": 1000,
            "upload_date": "20231215",
            "description": "Test video description",
            "formats": [
                {"format_id": "best", "ext": "mp4", "height": 1080}
            ],
            "thumbnails": [
                {"url": "https://example.com/thumb.jpg", "id": "0"}
            ],
            "requested_downloads": [
                {"filepath": "/test/path/video.mp4", "_filename": "video.mp4"}
            ]
        }
        
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.yt_dlp') as mock_yt_dlp:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl.__enter__.return_value = mock_ydl
            mock_ydl.__exit__.return_value = None
            mock_yt_dlp.YoutubeDL.return_value = mock_ydl
            yield mock_yt_dlp, mock_info
    
    @pytest.fixture
    def mock_ytdlp_error(self):
        """Mock yt-dlp error conditions."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.yt_dlp') as mock_yt_dlp:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = Exception("Download failed")
            mock_ydl.__enter__.return_value = mock_ydl
            mock_ydl.__exit__.return_value = None
            mock_yt_dlp.YoutubeDL.return_value = mock_ydl
            yield mock_yt_dlp
    
    def test_init(self, wrapper):
        """Test YtDlpWrapper initialization."""
        assert wrapper.default_quality == "best"
        assert wrapper.enable_logging is True
        assert isinstance(wrapper.default_output_dir, Path)
        assert isinstance(wrapper.downloads, dict)
    
    def test_init_without_ytdlp(self):
        """Test initialization when yt-dlp is not available."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.YTDLP_AVAILABLE', False):
            wrapper = YtDlpWrapper()
            # Should still initialize but with limited functionality
            assert wrapper.default_quality == "best"
    
    @pytest.mark.asyncio
    async def test_download_video_success(self, wrapper, mock_ytdlp_success):
        """Test successful video download."""
        mock_yt_dlp, mock_info = mock_ytdlp_success
        
        result = await wrapper.download_video(
            url="https://www.youtube.com/watch?v=test123",
            quality="720p",
            download_info_json=True
        )
        
        assert result["status"] == "success"
        assert result["video_info"]["title"] == "Test Video Title"
        assert result["video_info"]["duration"] == 300
        assert "download_id" in result
        
        # Verify yt-dlp was called
        mock_yt_dlp.YoutubeDL.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_download_video_error(self, wrapper, mock_ytdlp_error):
        """Test video download with error."""
        mock_yt_dlp = mock_ytdlp_error
        
        result = await wrapper.download_video(
            url="https://invalid-url.com/test"
        )
        
        assert result["status"] == "error"
        assert "error" in result
        assert "Download failed" in str(result["error"])
    
    @pytest.mark.asyncio
    async def test_download_video_without_ytdlp(self, wrapper):
        """Test download when yt-dlp is not available."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.YTDLP_AVAILABLE', False):
            result = await wrapper.download_video("https://example.com/test")
            
            assert result["status"] == "error"
            assert "not available" in result["error"]
    
    @pytest.mark.asyncio
    async def test_download_playlist_success(self, wrapper, mock_ytdlp_success):
        """Test successful playlist download."""
        mock_yt_dlp, mock_info = mock_ytdlp_success
        
        # Mock playlist info
        playlist_info = {
            **mock_info,
            "entries": [mock_info, mock_info],  # Two videos in playlist
            "_type": "playlist",
            "title": "Test Playlist"
        }
        mock_yt_dlp.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = playlist_info
        
        result = await wrapper.download_playlist(
            playlist_url="https://www.youtube.com/playlist?list=test123",
            max_downloads=2
        )
        
        assert result["status"] == "success"
        assert result["playlist_info"]["title"] == "Test Playlist"
        assert len(result["playlist_info"]["entries"]) == 2
    
    @pytest.mark.asyncio
    async def test_extract_info_success(self, wrapper, mock_ytdlp_success):
        """Test successful info extraction."""
        mock_yt_dlp, mock_info = mock_ytdlp_success
        
        result = await wrapper.extract_info(
            url="https://www.youtube.com/watch?v=test123",
            download=False
        )
        
        assert result["status"] == "success"
        assert result["video_info"]["title"] == "Test Video Title"
        assert result["video_info"]["uploader"] == "Test Channel"
        
        # Verify extract_info was called with download=False
        mock_yt_dlp.YoutubeDL.return_value.__enter__.return_value.extract_info.assert_called_with(
            "https://www.youtube.com/watch?v=test123", download=False
        )
    
    @pytest.mark.asyncio
    async def test_search_videos_success(self, wrapper, mock_ytdlp_success):
        """Test successful video search."""
        mock_yt_dlp, mock_info = mock_ytdlp_success
        
        # Mock search results
        search_results = {
            "entries": [mock_info, mock_info],
            "_type": "playlist",
            "title": "Search results"
        }
        mock_yt_dlp.YoutubeDL.return_value.__enter__.return_value.extract_info.return_value = search_results
        
        result = await wrapper.search_videos(
            query="test query",
            max_results=2,
            search_type="ytsearch"
        )
        
        assert result["status"] == "success"
        assert len(result["results"]) == 2
        assert result["query"] == "test query"
        assert result["max_results"] == 2
    
    @pytest.mark.asyncio
    async def test_batch_download_success(self, wrapper, mock_ytdlp_success):
        """Test successful batch download."""
        mock_yt_dlp, mock_info = mock_ytdlp_success
        
        urls = [
            "https://www.youtube.com/watch?v=test1",
            "https://www.youtube.com/watch?v=test2"
        ]
        
        result = await wrapper.batch_download(
            urls=urls,
            concurrent_downloads=2,
            ignore_errors=True
        )
        
        assert result["status"] == "success"
        assert result["total_requested"] == 2
        assert result["successful_downloads"] >= 0
        assert "results" in result
    
    @pytest.mark.asyncio
    async def test_batch_download_with_errors(self, wrapper):
        """Test batch download with some failures."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.yt_dlp') as mock_yt_dlp:
            # Mock mixed success/failure
            mock_ydl = MagicMock()
            mock_ydl.__enter__.return_value = mock_ydl
            mock_ydl.__exit__.return_value = None
            
            def extract_info_side_effect(url, download=True):
                if "fail" in url:
                    raise Exception("Download failed")
                return {"id": "test", "title": "Test"}
            
            mock_ydl.extract_info.side_effect = extract_info_side_effect
            mock_yt_dlp.YoutubeDL.return_value = mock_ydl
            
            urls = [
                "https://www.youtube.com/watch?v=success1",
                "https://www.youtube.com/watch?v=fail1",
                "https://www.youtube.com/watch?v=success2"
            ]
            
            result = await wrapper.batch_download(
                urls=urls,
                ignore_errors=True
            )
            
            assert result["status"] == "success"  # Some succeeded
            assert result["total_requested"] == 3
            assert result["failed_downloads"] > 0
    
    @pytest.mark.asyncio
    async def test_get_download_status(self, wrapper):
        """Test download status tracking."""
        # Add a mock download
        download_id = "test_download_123"
        wrapper.downloads[download_id] = {
            "status": "in_progress",
            "url": "https://example.com/test",
            "progress": 0.5,
            "start_time": 1234567890
        }
        
        status = await wrapper.get_download_status(download_id)
        
        assert status["status"] == "success"
        assert status["download_info"]["status"] == "in_progress"
        assert status["download_info"]["progress"] == 0.5
    
    @pytest.mark.asyncio
    async def test_get_download_status_not_found(self, wrapper):
        """Test getting status for non-existent download."""
        status = await wrapper.get_download_status("nonexistent_id")
        
        assert status["status"] == "error"
        assert "not found" in status["error"]
    
    @pytest.mark.asyncio
    async def test_cancel_download(self, wrapper):
        """Test download cancellation."""
        # Add a mock download
        download_id = "test_download_456"
        wrapper.downloads[download_id] = {
            "status": "in_progress",
            "url": "https://example.com/test"
        }
        
        result = await wrapper.cancel_download(download_id)
        
        assert result["status"] == "success"
        assert wrapper.downloads[download_id]["status"] == "cancelled"
    
    @pytest.mark.asyncio
    async def test_list_active_downloads(self, wrapper):
        """Test listing active downloads."""
        # Add mock downloads
        wrapper.downloads["dl1"] = {"status": "in_progress", "url": "https://example.com/1"}
        wrapper.downloads["dl2"] = {"status": "completed", "url": "https://example.com/2"}
        wrapper.downloads["dl3"] = {"status": "in_progress", "url": "https://example.com/3"}
        
        result = await wrapper.list_active_downloads()
        
        assert result["status"] == "success"
        assert result["total_downloads"] == 3
        assert result["active_downloads"] == 2  # Only in_progress ones
        assert len(result["downloads"]) == 2
    
    def test_validate_url(self, wrapper):
        """Test URL validation."""
        # Valid URLs
        assert wrapper._validate_url("https://www.youtube.com/watch?v=test") is True
        assert wrapper._validate_url("https://vimeo.com/12345") is True
        
        # Invalid URLs
        assert wrapper._validate_url("") is False
        assert wrapper._validate_url("not-a-url") is False
        assert wrapper._validate_url(None) is False
    
    def test_sanitize_filename(self, wrapper):
        """Test filename sanitization."""
        # Test various problematic characters
        result = wrapper._sanitize_filename("Test<>:\"/\\|?*File.mp4")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert result.endswith(".mp4")
        
        # Test empty filename
        result = wrapper._sanitize_filename("")
        assert result == "video"
        
        # Test very long filename
        long_name = "a" * 300 + ".mp4"
        result = wrapper._sanitize_filename(long_name)
        assert len(result) <= 255


class TestYtDlpWrapperIntegration:
    """Integration tests for YtDlpWrapper with more realistic scenarios."""
    
    @pytest.fixture
    def wrapper(self):
        """Create a wrapper instance for integration tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield YtDlpWrapper(
                default_output_dir=temp_dir,
                enable_logging=False  # Reduce noise in tests
            )
    
    @pytest.mark.asyncio
    async def test_download_with_custom_options(self, wrapper):
        """Test download with custom yt-dlp options."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.yt_dlp') as mock_yt_dlp:
            mock_ydl = MagicMock()
            mock_ydl.__enter__.return_value = mock_ydl
            mock_ydl.__exit__.return_value = None
            mock_ydl.extract_info.return_value = {
                "id": "test", "title": "Test",
                "requested_downloads": [{"filepath": "/test.mp4"}]
            }
            mock_yt_dlp.YoutubeDL.return_value = mock_ydl
            
            custom_opts = {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en", "es"]
            }
            
            result = await wrapper.download_video(
                url="https://example.com/test",
                custom_opts=custom_opts
            )
            
            assert result["status"] == "success"
            # Verify custom options were passed
            call_args = mock_yt_dlp.YoutubeDL.call_args[0][0]
            assert call_args["writesubtitles"] is True
            assert call_args["writeautomaticsub"] is True
            assert "en" in call_args["subtitleslangs"]
    
    @pytest.mark.asyncio  
    async def test_concurrent_downloads(self, wrapper):
        """Test concurrent download handling."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.yt_dlp') as mock_yt_dlp:
            # Mock async download behavior
            async def mock_download_delay(*args, **kwargs):
                await asyncio.sleep(0.1)  # Simulate download time
                return {
                    "id": "test", "title": "Test",
                    "requested_downloads": [{"filepath": "/test.mp4"}]
                }
            
            mock_ydl = MagicMock()
            mock_ydl.__enter__.return_value = mock_ydl
            mock_ydl.__exit__.return_value = None
            mock_ydl.extract_info.side_effect = lambda *args, **kwargs: {
                "id": "test", "title": "Test",
                "requested_downloads": [{"filepath": "/test.mp4"}]
            }
            mock_yt_dlp.YoutubeDL.return_value = mock_ydl
            
            urls = [f"https://example.com/test{i}" for i in range(5)]
            
            result = await wrapper.batch_download(
                urls=urls,
                concurrent_downloads=3
            )
            
            assert result["status"] == "success"
            assert result["total_requested"] == 5


class TestYtDlpWrapperErrorHandling:
    """Test error handling and edge cases."""
    
    @pytest.mark.asyncio
    async def test_invalid_url_handling(self):
        """Test handling of invalid URLs."""
        wrapper = YtDlpWrapper()
        
        # Test various invalid URL formats
        invalid_urls = [
            "",
            None,
            "not-a-url",
            "http://",
            "ftp://incomplete"
        ]
        
        for url in invalid_urls:
            result = await wrapper.download_video(url)
            assert result["status"] == "error"
            assert "invalid" in result["error"].lower() or "not available" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_network_timeout_handling(self, wrapper):
        """Test handling of network timeouts."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.yt_dlp') as mock_yt_dlp:
            mock_ydl = MagicMock()
            mock_ydl.__enter__.return_value = mock_ydl
            mock_ydl.__exit__.return_value = None
            mock_ydl.extract_info.side_effect = asyncio.TimeoutError("Network timeout")
            mock_yt_dlp.YoutubeDL.return_value = mock_ydl
            
            result = await wrapper.download_video(
                url="https://example.com/test",
                timeout=1
            )
            
            assert result["status"] == "error"
            assert "timeout" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_permission_error_handling(self, wrapper):
        """Test handling of file permission errors."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.yt_dlp') as mock_yt_dlp:
            mock_ydl = MagicMock()
            mock_ydl.__enter__.return_value = mock_ydl
            mock_ydl.__exit__.return_value = None
            mock_ydl.extract_info.side_effect = PermissionError("Permission denied")
            mock_yt_dlp.YoutubeDL.return_value = mock_ydl
            
            result = await wrapper.download_video("https://example.com/test")
            
            assert result["status"] == "error"
            assert "permission" in result["error"].lower()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
