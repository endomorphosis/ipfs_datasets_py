"""
Unit tests for the YT-DLP MCP server tools.

This test suite covers all MCP server tool functions for yt-dlp
including video downloads, playlist handling, info extraction, search,
and batch operations through the MCP interface.
"""

import asyncio
import json
import pytest
import tempfile
import unittest.mock
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

# Import the MCP tools under test
from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import (
    ytdlp_download_video,
    ytdlp_download_playlist,
    ytdlp_extract_info,
    ytdlp_search_videos,
    ytdlp_batch_download,
    main
)


class TestYtDlpMcpTools:
    """Test suite for YT-DLP MCP server tools."""
    
    @pytest.fixture
    def mock_successful_wrapper(self):
        """Mock a successful YtDlpWrapper."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            mock_instance = MagicMock()
            
            # Mock successful download_video
            mock_instance.download_video.return_value = {
                "status": "success",
                "video_info": {
                    "title": "Test Video",
                    "duration": 300,
                    "uploader": "Test Channel"
                },
                "output_path": "/test/video.mp4",
                "download_id": "test_123"
            }
            
            # Mock successful download_playlist
            mock_instance.download_playlist.return_value = {
                "status": "success",
                "playlist_info": {
                    "title": "Test Playlist",
                    "entries": [{"title": "Video 1"}, {"title": "Video 2"}]
                },
                "total_videos": 2,
                "downloaded_videos": 2
            }
            
            # Mock successful extract_info
            mock_instance.extract_info.return_value = {
                "status": "success",
                "video_info": {
                    "title": "Test Video Info",
                    "uploader": "Test Channel",
                    "duration": 300,
                    "view_count": 1000
                }
            }
            
            # Mock successful search_videos
            mock_instance.search_videos.return_value = {
                "status": "success",
                "results": [
                    {"title": "Result 1", "url": "https://example.com/1"},
                    {"title": "Result 2", "url": "https://example.com/2"}
                ],
                "query": "test query",
                "max_results": 2
            }
            
            # Mock successful batch_download
            mock_instance.batch_download.return_value = {
                "status": "success",
                "total_requested": 3,
                "successful_downloads": 2,
                "failed_downloads": 1,
                "results": [
                    {"status": "success", "url": "https://example.com/1"},
                    {"status": "success", "url": "https://example.com/2"},
                    {"status": "error", "url": "https://example.com/3", "error": "Failed"}
                ]
            }
            
            mock_wrapper.return_value = mock_instance
            yield mock_wrapper, mock_instance
    
    @pytest.fixture
    def mock_failing_wrapper(self):
        """Mock a failing YtDlpWrapper."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            mock_instance = MagicMock()
            
            # Mock all methods to return errors
            error_response = {
                "status": "error",
                "error": "Mock download failed"
            }
            
            mock_instance.download_video.return_value = error_response
            mock_instance.download_playlist.return_value = error_response
            mock_instance.extract_info.return_value = error_response
            mock_instance.search_videos.return_value = error_response
            mock_instance.batch_download.return_value = error_response
            
            mock_wrapper.return_value = mock_instance
            yield mock_wrapper, mock_instance


class TestYtdlpDownloadVideo:
    """Test ytdlp_download_video MCP tool."""
    
    @pytest.mark.asyncio
    async def test_download_video_success_single_url(self, mock_successful_wrapper):
        """Test successful single video download."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        result = await ytdlp_download_video(
            url="https://www.youtube.com/watch?v=test123",
            output_dir="/test/output",
            quality="720p",
            audio_only=False,
            download_info_json=True
        )
        
        assert result["status"] == "success"
        assert result["total_requested"] == 1
        assert result["successful_downloads"] == 1
        assert result["failed_downloads"] == 0
        assert len(result["results"]) == 1
        assert result["tool"] == "ytdlp_download_video"
        
        # Verify wrapper was called correctly
        mock_instance.download_video.assert_called_once()
        call_args = mock_instance.download_video.call_args
        assert call_args[0][0] == "https://www.youtube.com/watch?v=test123"
    
    @pytest.mark.asyncio
    async def test_download_video_success_multiple_urls(self, mock_successful_wrapper):
        """Test successful multiple video downloads."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        urls = [
            "https://www.youtube.com/watch?v=test1",
            "https://www.youtube.com/watch?v=test2"
        ]
        
        result = await ytdlp_download_video(
            url=urls,
            quality="best",
            extract_audio=True,
            audio_format="mp3"
        )
        
        assert result["status"] == "success"
        assert result["total_requested"] == 2
        assert result["successful_downloads"] == 2
        assert len(result["results"]) == 2
        
        # Verify wrapper was called for each URL
        assert mock_instance.download_video.call_count == 2
    
    @pytest.mark.asyncio
    async def test_download_video_without_ytdlp(self):
        """Test download when yt-dlp is not available."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', False):
            result = await ytdlp_download_video("https://example.com/test")
            
            assert result["status"] == "error"
            assert "not available" in result["error"]
            assert result["tool"] == "ytdlp_download_video"
    
    @pytest.mark.asyncio
    async def test_download_video_invalid_urls(self, mock_successful_wrapper):
        """Test download with invalid URLs."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        # Test empty URLs
        result = await ytdlp_download_video(url=[])
        assert result["status"] == "error"
        assert "Invalid URL" in result["error"]
        
        # Test None URLs
        result = await ytdlp_download_video(url=None)
        assert result["status"] == "error"
        assert "Invalid URL" in result["error"]
        
        # Test URLs with empty strings
        result = await ytdlp_download_video(url=["", "  "])
        assert result["status"] == "error"
        assert "Invalid URL" in result["error"]
    
    @pytest.mark.asyncio
    async def test_download_video_wrapper_error(self, mock_failing_wrapper):
        """Test download when wrapper returns error."""
        mock_wrapper, mock_instance = mock_failing_wrapper
        
        result = await ytdlp_download_video("https://example.com/test")
        
        assert result["status"] == "success"  # Overall success even with individual failures
        assert result["failed_downloads"] == 1
        assert len(result["failed_results"]) == 1
        assert "Mock download failed" in str(result["failed_results"][0]["error"])
    
    @pytest.mark.asyncio
    async def test_download_video_exception(self):
        """Test download with unexpected exception."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            mock_wrapper.side_effect = Exception("Unexpected error")
            
            result = await ytdlp_download_video("https://example.com/test")
            
            assert result["status"] == "error"
            assert "Unexpected error" in result["error"]
            assert result["tool"] == "ytdlp_download_video"


class TestYtdlpDownloadPlaylist:
    """Test ytdlp_download_playlist MCP tool."""
    
    @pytest.mark.asyncio
    async def test_download_playlist_success(self, mock_successful_wrapper):
        """Test successful playlist download."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        result = await ytdlp_download_playlist(
            playlist_url="https://www.youtube.com/playlist?list=test123",
            output_dir="/test/output",
            quality="best",
            max_downloads=10,
            start_index=1,
            end_index=5
        )
        
        assert result["status"] == "success"
        assert result["playlist_info"]["title"] == "Test Playlist"
        assert result["total_videos"] == 2
        assert result["tool"] == "ytdlp_download_playlist"
        
        # Verify wrapper was called correctly
        mock_instance.download_playlist.assert_called_once()
        call_args = mock_instance.download_playlist.call_args
        assert call_args[0][0] == "https://www.youtube.com/playlist?list=test123"
        assert call_args[1]["max_downloads"] == 10
        assert call_args[1]["start_index"] == 1
        assert call_args[1]["end_index"] == 5
    
    @pytest.mark.asyncio
    async def test_download_playlist_without_ytdlp(self):
        """Test playlist download when yt-dlp is not available."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', False):
            result = await ytdlp_download_playlist("https://example.com/playlist")
            
            assert result["status"] == "error"
            assert "not available" in result["error"]
            assert result["tool"] == "ytdlp_download_playlist"
    
    @pytest.mark.asyncio
    async def test_download_playlist_invalid_url(self, mock_successful_wrapper):
        """Test playlist download with invalid URL."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        # Test empty URL
        result = await ytdlp_download_playlist("")
        assert result["status"] == "error"
        assert "Invalid playlist URL" in result["error"]
        
        # Test None URL
        result = await ytdlp_download_playlist(None)
        assert result["status"] == "error"
        assert "Invalid playlist URL" in result["error"]
    
    @pytest.mark.asyncio
    async def test_download_playlist_with_custom_options(self, mock_successful_wrapper):
        """Test playlist download with custom options."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        custom_opts = {
            "writesubtitles": True,
            "subtitleslangs": ["en", "es"]
        }
        
        result = await ytdlp_download_playlist(
            playlist_url="https://example.com/playlist",
            custom_opts=custom_opts
        )
        
        assert result["status"] == "success"
        
        # Verify custom options were passed
        call_kwargs = mock_instance.download_playlist.call_args[1]
        assert call_kwargs["writesubtitles"] is True
        assert "en" in call_kwargs["subtitleslangs"]


class TestYtdlpExtractInfo:
    """Test ytdlp_extract_info MCP tool."""
    
    @pytest.mark.asyncio
    async def test_extract_info_success(self, mock_successful_wrapper):
        """Test successful info extraction."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        result = await ytdlp_extract_info(
            url="https://www.youtube.com/watch?v=test123",
            download=False,
            extract_flat=True,
            include_subtitles=True
        )
        
        assert result["status"] == "success"
        assert result["video_info"]["title"] == "Test Video Info"
        assert result["video_info"]["uploader"] == "Test Channel"
        assert result["tool"] == "ytdlp_extract_info"
        
        # Verify wrapper was called correctly
        mock_instance.extract_info.assert_called_once()
        call_args = mock_instance.extract_info.call_args
        assert call_args[0][0] == "https://www.youtube.com/watch?v=test123"
        assert call_args[1]["download"] is False
        assert call_args[1]["extract_flat"] is True
        assert call_args[1]["include_subtitles"] is True
    
    @pytest.mark.asyncio
    async def test_extract_info_without_ytdlp(self):
        """Test info extraction when yt-dlp is not available."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', False):
            result = await ytdlp_extract_info("https://example.com/test")
            
            assert result["status"] == "error"
            assert "not available" in result["error"]
            assert result["tool"] == "ytdlp_extract_info"
    
    @pytest.mark.asyncio
    async def test_extract_info_invalid_url(self, mock_successful_wrapper):
        """Test info extraction with invalid URL."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        # Test empty URL
        result = await ytdlp_extract_info("")
        assert result["status"] == "error"
        assert "Invalid URL" in result["error"]
        
        # Test None URL
        result = await ytdlp_extract_info(None)
        assert result["status"] == "error"
        assert "Invalid URL" in result["error"]


class TestYtdlpSearchVideos:
    """Test ytdlp_search_videos MCP tool."""
    
    @pytest.mark.asyncio
    async def test_search_videos_success(self, mock_successful_wrapper):
        """Test successful video search."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        result = await ytdlp_search_videos(
            query="test search query",
            max_results=5,
            search_type="ytsearch",
            extract_info=True
        )
        
        assert result["status"] == "success"
        assert len(result["results"]) == 2
        assert result["query"] == "test query"  # From mock
        assert result["tool"] == "ytdlp_search_videos"
        
        # Verify wrapper was called correctly
        mock_instance.search_videos.assert_called_once()
        call_args = mock_instance.search_videos.call_args
        assert call_args[1]["query"] == "test search query"
        assert call_args[1]["max_results"] == 5
        assert call_args[1]["search_type"] == "ytsearch"
        assert call_args[1]["extract_info"] is True
    
    @pytest.mark.asyncio
    async def test_search_videos_without_ytdlp(self):
        """Test video search when yt-dlp is not available."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', False):
            result = await ytdlp_search_videos("test query")
            
            assert result["status"] == "error"
            assert "not available" in result["error"]
            assert result["tool"] == "ytdlp_search_videos"
    
    @pytest.mark.asyncio
    async def test_search_videos_invalid_query(self, mock_successful_wrapper):
        """Test video search with invalid query."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        # Test empty query
        result = await ytdlp_search_videos("")
        assert result["status"] == "error"
        assert "Invalid search query" in result["error"]
        
        # Test None query
        result = await ytdlp_search_videos(None)
        assert result["status"] == "error"
        assert "Invalid search query" in result["error"]


class TestYtdlpBatchDownload:
    """Test ytdlp_batch_download MCP tool."""
    
    @pytest.mark.asyncio
    async def test_batch_download_success(self, mock_successful_wrapper):
        """Test successful batch download."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        urls = [
            "https://www.youtube.com/watch?v=test1",
            "https://www.youtube.com/watch?v=test2",
            "https://www.youtube.com/watch?v=test3"
        ]
        
        result = await ytdlp_batch_download(
            urls=urls,
            output_dir="/test/output",
            quality="720p",
            concurrent_downloads=2,
            ignore_errors=True
        )
        
        assert result["status"] == "success"
        assert result["total_requested"] == 3
        assert result["successful_downloads"] == 2
        assert result["failed_downloads"] == 1
        assert result["tool"] == "ytdlp_batch_download"
        
        # Verify wrapper was called correctly
        mock_instance.batch_download.assert_called_once()
        call_args = mock_instance.batch_download.call_args
        assert call_args[0][0] == urls
        assert call_args[1]["concurrent_downloads"] == 2
        assert call_args[1]["ignore_errors"] is True
    
    @pytest.mark.asyncio
    async def test_batch_download_without_ytdlp(self):
        """Test batch download when yt-dlp is not available."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', False):
            result = await ytdlp_batch_download(["https://example.com/test"])
            
            assert result["status"] == "error"
            assert "not available" in result["error"]
            assert result["tool"] == "ytdlp_batch_download"
    
    @pytest.mark.asyncio
    async def test_batch_download_invalid_urls(self, mock_successful_wrapper):
        """Test batch download with invalid URLs."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        # Test empty list
        result = await ytdlp_batch_download([])
        assert result["status"] == "error"
        assert "Invalid URLs list" in result["error"]
        
        # Test None
        result = await ytdlp_batch_download(None)
        assert result["status"] == "error"
        assert "Invalid URLs list" in result["error"]
        
        # Test non-list
        result = await ytdlp_batch_download("not-a-list")
        assert result["status"] == "error"
        assert "Invalid URLs list" in result["error"]


class TestMcpToolMain:
    """Test the main function for MCP tool registration."""
    
    @pytest.mark.asyncio
    async def test_main_function(self):
        """Test the main function returns correct tool information."""
        result = await main()
        
        assert result["status"] == "success"
        assert "YT-DLP download tools initialized" in result["message"]
        assert len(result["tools"]) == 5
        assert "ytdlp_download_video" in result["tools"]
        assert "ytdlp_download_playlist" in result["tools"]
        assert "ytdlp_extract_info" in result["tools"]
        assert "ytdlp_search_videos" in result["tools"]
        assert "ytdlp_batch_download" in result["tools"]
        assert "1000+ sites" in result["supported_sites"]


class TestMcpToolsIntegration:
    """Integration tests for MCP tools."""
    
    @pytest.mark.asyncio
    async def test_tool_error_handling_consistency(self, mock_failing_wrapper):
        """Test that all tools handle errors consistently."""
        mock_wrapper, mock_instance = mock_failing_wrapper
        
        # Test each tool handles errors consistently
        tools_and_args = [
            (ytdlp_download_video, ["https://example.com/test"]),
            (ytdlp_download_playlist, ["https://example.com/playlist"]),
            (ytdlp_extract_info, ["https://example.com/test"]),
            (ytdlp_search_videos, ["test query"]),
            (ytdlp_batch_download, [["https://example.com/test"]])
        ]
        
        for tool_func, args in tools_and_args:
            with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', True):
                result = await tool_func(*args)
                
                # Each tool should have a "tool" field identifying itself
                assert "tool" in result
                assert result["tool"].startswith("ytdlp_")
    
    @pytest.mark.asyncio
    async def test_tool_parameter_validation(self, mock_successful_wrapper):
        """Test parameter validation across all tools."""
        mock_wrapper, mock_instance = mock_successful_wrapper
        
        # Test that tools validate their required parameters
        result = await ytdlp_download_video("")
        assert result["status"] == "error"
        
        result = await ytdlp_download_playlist("")
        assert result["status"] == "error"
        
        result = await ytdlp_extract_info("")
        assert result["status"] == "error"
        
        result = await ytdlp_search_videos("")
        assert result["status"] == "error"
        
        result = await ytdlp_batch_download([])
        assert result["status"] == "error"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
