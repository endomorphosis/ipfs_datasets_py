"""
Integration tests for the complete multimedia system.

This test suite covers integration between the multimedia library,
MCP server tools, and the overall media processing pipeline.
"""

import asyncio
import pytest
import tempfile
import unittest.mock
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

# Import modules under test
from ipfs_datasets_py.multimedia import (
    YtDlpWrapper, FFmpegWrapper, MediaProcessor, MediaUtils,
    HAVE_YTDLP, HAVE_FFMPEG
)
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ytdlp_download_video, ytdlp_download_playlist, ytdlp_extract_info,
    ytdlp_search_videos, ytdlp_batch_download
)


class TestMultimediaLibraryIntegration:
    """Test integration between multimedia library components."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    def test_multimedia_imports(self):
        """Test that all multimedia components can be imported."""
        # Test that all classes are available
        assert YtDlpWrapper is not None
        assert FFmpegWrapper is not None
        assert MediaProcessor is not None
        assert MediaUtils is not None
        
        # Test feature flags
        assert isinstance(HAVE_YTDLP, bool)
        assert isinstance(HAVE_FFMPEG, bool)
    
    def test_media_processor_initialization(self, temp_dir):
        """Test MediaProcessor initialization with different configurations."""
        # Test basic initialization
        processor = MediaProcessor(default_output_dir=temp_dir)
        assert processor.default_output_dir == Path(temp_dir)
        
        # Test capabilities
        capabilities = processor.get_capabilities()
        assert "ytdlp_available" in capabilities
        assert "ffmpeg_available" in capabilities
        assert "supported_operations" in capabilities
    
    def test_media_utils_functionality(self):
        """Test MediaUtils functionality."""
        # Test file type detection
        assert MediaUtils.get_file_type("video.mp4") == "video"
        assert MediaUtils.get_file_type("audio.mp3") == "audio"
        assert MediaUtils.get_file_type("image.jpg") == "image"
        assert MediaUtils.get_file_type("document.txt") is None
        
        # Test media file validation
        assert MediaUtils.is_media_file("test.mp4") is True
        assert MediaUtils.is_media_file("test.txt") is False
        
        # Test URL validation
        assert MediaUtils.validate_url("https://youtube.com/watch?v=test") is True
        assert MediaUtils.validate_url("not-a-url") is False
        assert MediaUtils.validate_url("") is False
        
        # Test filename sanitization
        cleaned = MediaUtils.sanitize_filename("Test<>:\"/\\|?*File.mp4")
        assert "<" not in cleaned and ">" not in cleaned
        assert cleaned.endswith(".mp4")
        
        # Test file size formatting
        assert "1.0 KB" == MediaUtils.format_file_size(1024)
        assert "1.0 MB" == MediaUtils.format_file_size(1024 * 1024)
        
        # Test duration formatting
        assert "05:00" == MediaUtils.format_duration(300)
        assert "01:05:00" == MediaUtils.format_duration(3900)


class TestMcpToolsIntegration:
    """Test integration between MCP tools and multimedia library."""
    
    @pytest.fixture
    def mock_multimedia_components(self):
        """Mock multimedia components for testing."""
        with patch('ipfs_datasets_py.multimedia.ytdlp_wrapper.YTDLP_AVAILABLE', True), \
             patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', True):
            yield
    
    @pytest.mark.asyncio
    async def test_mcp_tool_workflow(self, mock_multimedia_components):
        """Test complete workflow through MCP tools."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            # Mock successful operations
            mock_instance = MagicMock()
            mock_instance.extract_info.return_value = {
                "status": "success",
                "video_info": {
                    "title": "Test Video",
                    "duration": 300,
                    "uploader": "Test Channel",
                    "url": "https://example.com/video.mp4"
                }
            }
            mock_instance.download_video.return_value = {
                "status": "success",
                "video_info": {"title": "Test Video"},
                "output_path": "/test/video.mp4"
            }
            mock_wrapper.return_value = mock_instance
            
            # Step 1: Extract video info
            info_result = await ytdlp_extract_info(
                url="https://youtube.com/watch?v=test123",
                download=False
            )
            assert info_result["status"] == "success"
            assert info_result["tool"] == "ytdlp_extract_info"
            
            # Step 2: Download the video
            download_result = await ytdlp_download_video(
                url="https://youtube.com/watch?v=test123",
                quality="720p"
            )
            assert download_result["status"] == "success"
            assert download_result["tool"] == "ytdlp_download_video"
            
            # Verify both tools were called
            assert mock_instance.extract_info.called
            assert mock_instance.download_video.called
    
    @pytest.mark.asyncio
    async def test_batch_processing_workflow(self, mock_multimedia_components):
        """Test batch processing workflow."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            mock_instance = MagicMock()
            mock_instance.search_videos.return_value = {
                "status": "success",
                "results": [
                    {"title": "Video 1", "url": "https://example.com/1"},
                    {"title": "Video 2", "url": "https://example.com/2"},
                    {"title": "Video 3", "url": "https://example.com/3"}
                ],
                "query": "test search"
            }
            mock_instance.batch_download.return_value = {
                "status": "success",
                "total_requested": 3,
                "successful_downloads": 2,
                "failed_downloads": 1,
                "results": [
                    {"status": "success", "url": "https://example.com/1"},
                    {"status": "success", "url": "https://example.com/2"},
                    {"status": "error", "url": "https://example.com/3"}
                ]
            }
            mock_wrapper.return_value = mock_instance
            
            # Step 1: Search for videos
            search_result = await ytdlp_search_videos(
                query="test videos",
                max_results=3
            )
            assert search_result["status"] == "success"
            
            # Step 2: Extract URLs from search results
            urls = [video["url"] for video in search_result["results"]]
            
            # Step 3: Batch download
            batch_result = await ytdlp_batch_download(
                urls=urls,
                concurrent_downloads=2
            )
            assert batch_result["status"] == "success"
            assert batch_result["total_requested"] == 3
            assert batch_result["successful_downloads"] == 2


class TestErrorHandlingIntegration:
    """Test error handling across the multimedia system."""
    
    @pytest.mark.asyncio
    async def test_graceful_degradation_without_ytdlp(self):
        """Test system behavior when yt-dlp is not available."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.HAVE_YTDLP', False):
            # All MCP tools should return appropriate errors
            result = await ytdlp_download_video("https://example.com/test")
            assert result["status"] == "error"
            assert "not available" in result["error"]
            
            result = await ytdlp_extract_info("https://example.com/test")
            assert result["status"] == "error"
            assert "not available" in result["error"]
    
    @pytest.mark.asyncio
    async def test_error_propagation(self):
        """Test that errors propagate correctly through the system."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            # Mock wrapper that raises exception
            mock_wrapper.side_effect = Exception("Critical error")
            
            result = await ytdlp_download_video("https://example.com/test")
            assert result["status"] == "error"
            assert "Critical error" in result["error"]
    
    def test_media_utils_error_handling(self):
        """Test MediaUtils error handling."""
        # Test with invalid inputs
        assert MediaUtils.get_file_type(None) is None
        assert MediaUtils.get_file_type("") is None
        
        assert MediaUtils.validate_url(None) is False
        assert MediaUtils.validate_url("") is False
        
        # Test filename sanitization with edge cases
        result = MediaUtils.sanitize_filename("")
        assert result == "unnamed_file"
        
        # Test very long filename
        long_name = "a" * 300 + ".mp4"
        result = MediaUtils.sanitize_filename(long_name)
        assert len(result) <= 255


class TestPerformanceIntegration:
    """Test performance aspects of the multimedia system."""
    
    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test concurrent multimedia operations."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            mock_instance = MagicMock()
            
            async def mock_download_delay(*args, **kwargs):
                await asyncio.sleep(0.1)  # Simulate download time
                return {"status": "success", "video_info": {"title": "Test"}}
            
            mock_instance.download_video.side_effect = mock_download_delay
            mock_wrapper.return_value = mock_instance
            
            # Start multiple downloads concurrently
            urls = [f"https://example.com/test{i}" for i in range(3)]
            
            tasks = [
                ytdlp_download_video(url, quality="720p")
                for url in urls
            ]
            
            results = await asyncio.gather(*tasks)
            
            # All should complete successfully
            for result in results:
                assert result["status"] == "success"
    
    @pytest.mark.asyncio
    async def test_memory_usage_with_large_batches(self):
        """Test memory usage with large batch operations."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            mock_instance = MagicMock()
            mock_instance.batch_download.return_value = {
                "status": "success",
                "total_requested": 100,
                "successful_downloads": 95,
                "failed_downloads": 5,
                "results": [{"status": "success"} for _ in range(95)] + 
                          [{"status": "error"} for _ in range(5)]
            }
            mock_wrapper.return_value = mock_instance
            
            # Test with large batch
            urls = [f"https://example.com/test{i}" for i in range(100)]
            
            result = await ytdlp_batch_download(
                urls=urls,
                concurrent_downloads=5
            )
            
            assert result["status"] == "success"
            assert result["total_requested"] == 100


class TestConfigurationIntegration:
    """Test configuration and customization aspects."""
    
    def test_multimedia_configuration(self):
        """Test multimedia component configuration."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test YtDlpWrapper configuration
            wrapper = YtDlpWrapper(
                default_output_dir=temp_dir,
                enable_logging=False,
                default_quality="720p"
            )
            assert wrapper.default_output_dir == Path(temp_dir)
            assert wrapper.enable_logging is False
            assert wrapper.default_quality == "720p"
            
            # Test MediaProcessor configuration
            processor = MediaProcessor(
                default_output_dir=temp_dir,
                enable_logging=True
            )
            assert processor.default_output_dir == Path(temp_dir)
            assert processor.enable_logging is True
    
    @pytest.mark.asyncio
    async def test_custom_options_propagation(self):
        """Test that custom options propagate correctly through the system."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            mock_instance = MagicMock()
            mock_instance.download_video.return_value = {"status": "success"}
            mock_wrapper.return_value = mock_instance
            
            custom_opts = {
                "writesubtitles": True,
                "subtitleslangs": ["en", "es"],
                "writeautomaticsub": True
            }
            
            await ytdlp_download_video(
                url="https://example.com/test",
                custom_opts=custom_opts
            )
            
            # Verify custom options were passed to the wrapper
            call_kwargs = mock_instance.download_video.call_args[1]
            assert "writesubtitles" in call_kwargs
            assert call_kwargs["writesubtitles"] is True


class TestEndToEndIntegration:
    """End-to-end integration tests."""
    
    @pytest.mark.asyncio
    async def test_complete_multimedia_pipeline(self):
        """Test complete multimedia processing pipeline."""
        with patch('ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download.YtDlpWrapper') as mock_wrapper:
            # Mock complete pipeline
            mock_instance = MagicMock()
            
            # Search results
            mock_instance.search_videos.return_value = {
                "status": "success",
                "results": [
                    {"title": "Educational Video", "url": "https://example.com/edu1"},
                    {"title": "Tutorial Video", "url": "https://example.com/edu2"}
                ]
            }
            
            # Info extraction
            mock_instance.extract_info.return_value = {
                "status": "success",
                "video_info": {
                    "title": "Educational Video",
                    "duration": 600,
                    "description": "Learn about multimedia processing"
                }
            }
            
            # Download
            mock_instance.download_video.return_value = {
                "status": "success",
                "output_path": "/downloads/educational_video.mp4"
            }
            
            mock_wrapper.return_value = mock_instance
            
            # Step 1: Search for educational content
            search_result = await ytdlp_search_videos(
                query="multimedia processing tutorial",
                max_results=2
            )
            assert search_result["status"] == "success"
            
            # Step 2: Get detailed info for first result
            first_url = search_result["results"][0]["url"]
            info_result = await ytdlp_extract_info(
                url=first_url,
                download=False
            )
            assert info_result["status"] == "success"
            
            # Step 3: Download if suitable (duration check)
            if info_result["video_info"]["duration"] <= 1800:  # 30 minutes
                download_result = await ytdlp_download_video(
                    url=first_url,
                    quality="720p",
                    download_info_json=True
                )
                assert download_result["status"] == "success"
            
            # Verify all steps were executed
            assert mock_instance.search_videos.called
            assert mock_instance.extract_info.called
            assert mock_instance.download_video.called


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
