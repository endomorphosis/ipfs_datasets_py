#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import anyio
from unittest.mock import AsyncMock
from urllib.parse import urlparse

# Import the MediaProcessor class
from ipfs_datasets_py.multimedia.media_processor import make_media_processor

# Test data constants - Using stable, public test videos
PLATFORM_TEST_URLS = {
    "youtube": "https://www.youtube.com/watch?v=BaW_jenozKc",  # YouTube test video
    "vimeo": "https://vimeo.com/148751763",  # Vimeo test video
    "dailymotion": "https://www.dailymotion.com/video/x2hwqn9",  # Public test video
    "archive_org": "https://archive.org/details/BigBuckBunny_124",  # Internet Archive test
    "peertube": "https://framatube.org/w/9c9de5e8-0a1e-484a-b099-e80766180a6d",  # Framatube instance
}

SUCCESS_STATUS = "success"
ERROR_STATUS = "error"
FACEBOOK_TEST_URL = "https://facebook.com/video/123"
INSTAGRAM_TEST_URL = "https://instagram.com/p/abc123"
TWITTER_TEST_URL = "https://twitter.com/user/status/123"


class TestPlatformSupportCoverage:
    """
    Tests for MediaProcessor.download_and_convert() method with various platform URLs.
    
    Focuses on URL processing behavior and response validation for different video platforms.
    Tests both successful processing and error handling scenarios using mocked backends.
    """

    @pytest.mark.asyncio
    async def test_youtube_url_processing_has_status_field(self, mock_processor):
        """
        GIVEN YouTube URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect response contains status field
        """
        # Arrange
        youtube_url = PLATFORM_TEST_URLS["youtube"]
        
        # Act
        result = await mock_processor.download_and_convert(youtube_url)
        
        # Assert
        assert "status" in result, f"Expected 'status' field in response, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_youtube_url_processing_status_value_valid(self, mock_processor):
        """
        GIVEN YouTube URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect status field has either success 
        """
        # Arrange
        youtube_url = PLATFORM_TEST_URLS["youtube"]
        
        # Act
        result = await mock_processor.download_and_convert(youtube_url)
        
        # Assert
        assert result["status"] in SUCCESS_STATUS, f"Expected status to be '{SUCCESS_STATUS}' or '{ERROR_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_vimeo_url_processing_has_status_field(self, mock_processor):
        """
        GIVEN Vimeo URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect response contains status field
        """
        # Arrange
        vimeo_url = PLATFORM_TEST_URLS["vimeo"]
        
        # Act
        result = await mock_processor.download_and_convert(vimeo_url)
        
        # Assert
        assert "status" in result, f"Expected 'status' field in response, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_vimeo_url_processing_status_value_valid(self, mock_processor):
        """
        GIVEN Vimeo URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect status field has either success 
        """
        # Arrange
        vimeo_url = PLATFORM_TEST_URLS["vimeo"]
        
        # Act
        result = await mock_processor.download_and_convert(vimeo_url)
        
        # Assert
        assert result["status"] in  SUCCESS_STATUS, f"Expected status to be '{SUCCESS_STATUS}' or '{ERROR_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_dailymotion_url_processing_has_status_field(self, mock_processor):
        """
        GIVEN Dailymotion URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect response contains status field
        """
        # Arrange
        dailymotion_url = PLATFORM_TEST_URLS["dailymotion"]
        
        # Act
        result = await mock_processor.download_and_convert(dailymotion_url)
        
        # Assert
        assert "status" in result, f"Expected 'status' field in response, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_dailymotion_url_processing_status_value_valid(self, mock_processor):
        """
        GIVEN Dailymotion URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect status field has either success 
        """
        # Arrange
        dailymotion_url = PLATFORM_TEST_URLS["dailymotion"]
        
        # Act
        result = await mock_processor.download_and_convert(dailymotion_url)
        
        # Assert
        assert result["status"] in  SUCCESS_STATUS, f"Expected status to be '{SUCCESS_STATUS}' or '{ERROR_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_archive_org_url_processing_has_status_field(self, mock_processor):
        """
        GIVEN Archive.org URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect response contains status field
        """
        # Arrange
        archive_url = PLATFORM_TEST_URLS["archive_org"]
        
        # Act
        result = await mock_processor.download_and_convert(archive_url)
        
        # Assert
        assert "status" in result, f"Expected 'status' field in response, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_archive_org_url_processing_status_value_valid(self, mock_processor):
        """
        GIVEN Archive.org URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect status field has either success 
        """
        # Arrange
        archive_url = PLATFORM_TEST_URLS["archive_org"]
        
        # Act
        result = await mock_processor.download_and_convert(archive_url)
        
        # Assert
        assert result["status"] in  SUCCESS_STATUS, f"Expected status to be '{SUCCESS_STATUS}' or '{ERROR_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_peertube_url_processing_has_status_field(self, mock_processor):
        """
        GIVEN PeerTube URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect response contains status field
        """
        # Arrange
        peertube_url = PLATFORM_TEST_URLS["peertube"]
        
        # Act
        result = await mock_processor.download_and_convert(peertube_url)
        
        # Assert
        assert "status" in result, f"Expected 'status' field in response, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_peertube_url_processing_status_value_valid(self, mock_processor):
        """
        GIVEN PeerTube URL from PLATFORM_TEST_URLS
        WHEN MediaProcessor.download_and_convert() is called with the URL
        THEN expect status field has either success 
        """
        # Arrange
        peertube_url = PLATFORM_TEST_URLS["peertube"]
        
        # Act
        result = await mock_processor.download_and_convert(peertube_url)
        
        # Assert
        assert result["status"] in  SUCCESS_STATUS, f"Expected status to be '{SUCCESS_STATUS}' or '{ERROR_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_facebook_url_with_mocked_response_status_success(self, tmp_path, mock_factory):
        """
        GIVEN Facebook video URL and mocked yt-dlp response containing typical Facebook metadata
        WHEN MediaProcessor.download_and_convert() is called with mocked backend
        THEN expect response status is success
        """
        # Arrange
        facebook_metadata = {
            "status": SUCCESS_STATUS,
            "output_path": str(tmp_path / "facebook_video.mp4"),
            "title": "Facebook Test Video",
            "duration": 300.0,
            "filesize": 2048000,
            "format": "mp4"
        }
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs=facebook_metadata
        )
        
        # Act
        result = await processor.download_and_convert(FACEBOOK_TEST_URL)
        
        # Assert
        assert result["status"] == SUCCESS_STATUS, f"Expected status '{SUCCESS_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_facebook_url_with_mocked_response_contains_title(self, tmp_path, mock_factory):
        """
        GIVEN Facebook video URL and mocked yt-dlp response containing typical Facebook metadata
        WHEN MediaProcessor.download_and_convert() is called with mocked backend
        THEN expect response contains mocked title
        """
        # Arrange
        facebook_metadata = {
            "status": SUCCESS_STATUS,
            "output_path": str(tmp_path / "facebook_video.mp4"),
            "title": "Facebook Test Video",
            "duration": 300.0,
            "filesize": 2048000,
            "format": "mp4"
        }
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs=facebook_metadata
        )
        
        # Act
        result = await processor.download_and_convert(FACEBOOK_TEST_URL)
        
        # Assert
        assert result["title"] == facebook_metadata["title"], f"Expected title '{facebook_metadata['title']}', got: {result.get('title')}"

    @pytest.mark.asyncio
    async def test_instagram_url_with_mocked_response_status_success(self, tmp_path, mock_factory):
        """
        GIVEN Instagram video URL and mocked yt-dlp response containing typical Instagram metadata
        WHEN MediaProcessor.download_and_convert() is called with mocked backend
        THEN expect response status is success
        """
        # Arrange
        instagram_metadata = {
            "status": SUCCESS_STATUS,
            "output_path": str(tmp_path / "instagram_video.mp4"),
            "title": "Instagram Test Video",
            "duration": 180.0,
            "filesize": 1536000,
            "format": "mp4"
        }
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs=instagram_metadata
        )
        
        # Act
        result = await processor.download_and_convert(INSTAGRAM_TEST_URL)
        
        # Assert
        assert result["status"] == SUCCESS_STATUS, f"Expected status '{SUCCESS_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_instagram_url_with_mocked_response_contains_title(self, tmp_path, mock_factory):
        """
        GIVEN Instagram video URL and mocked yt-dlp response containing typical Instagram metadata
        WHEN MediaProcessor.download_and_convert() is called with mocked backend
        THEN expect response contains mocked title
        """
        # Arrange
        instagram_metadata = {
            "status": SUCCESS_STATUS,
            "output_path": str(tmp_path / "instagram_video.mp4"),
            "title": "Instagram Test Video",
            "duration": 180.0,
            "filesize": 1536000,
            "format": "mp4"
        }
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs=instagram_metadata
        )
        
        # Act
        result = await processor.download_and_convert(INSTAGRAM_TEST_URL)
        
        # Assert
        assert result["title"] == instagram_metadata["title"], f"Expected title '{instagram_metadata['title']}', got: {result.get('title')}"

    @pytest.mark.asyncio
    async def test_twitter_url_with_mocked_response_status_success(self, tmp_path, mock_factory):
        """
        GIVEN Twitter/X video URL and mocked yt-dlp response containing typical Twitter metadata
        WHEN MediaProcessor.download_and_convert() is called with mocked backend
        THEN expect response status is success
        """
        # Arrange
        twitter_metadata = {
            "status": SUCCESS_STATUS,
            "output_path": str(tmp_path / "twitter_video.mp4"),
            "title": "Twitter Test Video",
            "duration": 90.0,
            "filesize": 1024000,
            "format": "mp4"
        }
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs=twitter_metadata
        )
        
        # Act
        result = await processor.download_and_convert(TWITTER_TEST_URL)
        
        # Assert
        assert result["status"] == SUCCESS_STATUS, f"Expected status '{SUCCESS_STATUS}', got: {result['status']}"

    @pytest.mark.asyncio
    async def test_twitter_url_with_mocked_response_contains_title(self, tmp_path, mock_factory):
        """
        GIVEN Twitter/X video URL and mocked yt-dlp response containing typical Twitter metadata
        WHEN MediaProcessor.download_and_convert() is called with mocked backend
        THEN expect response contains mocked title
        """
        # Arrange
        twitter_metadata = {
            "status": SUCCESS_STATUS,
            "output_path": str(tmp_path / "twitter_video.mp4"),
            "title": "Twitter Test Video",
            "duration": 90.0,
            "filesize": 1024000,
            "format": "mp4"
        }
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs=twitter_metadata
        )
        
        # Act
        result = await processor.download_and_convert(TWITTER_TEST_URL)
        
        # Assert
        assert result["title"] == twitter_metadata["title"], f"Expected title '{twitter_metadata['title']}', got: {result.get('title')}"

    @pytest.mark.asyncio
    async def test_response_title_field_type_when_present(self, processor_with_title, test_url):
        """
        GIVEN successful MediaProcessor.download_and_convert() call that returns metadata
        WHEN checking the title field in the response
        THEN expect title field to be a string type
        """
        # Arrange & Act
        result = await processor_with_title.download_and_convert(test_url)
        
        # Assert
        assert isinstance(result["title"], str), f"Expected title to be str type, got: {type(result['title'])}"

    @pytest.mark.asyncio
    async def test_response_duration_field_type_when_present(self, processor_with_duration, test_url):
        """
        GIVEN successful MediaProcessor.download_and_convert() call that returns metadata
        WHEN checking the duration field in the response
        THEN expect duration field to be float type
        """
        # Arrange & Act
        result = await processor_with_duration.download_and_convert(test_url)
        
        # Assert
        assert isinstance(result["duration"], float), f"Expected duration to be float, got: {type(result['duration'])}"

    @pytest.mark.asyncio
    async def test_response_duration_field_value_when_present(self, processor_with_duration, test_url):
        """
        GIVEN successful MediaProcessor.download_and_convert() call that returns metadata
        WHEN checking the duration field in the response
        THEN expect duration field to be ≥ 0
        """
        # Arrange & Act
        result = await processor_with_duration.download_and_convert(test_url)
        
        # Assert
        assert result["duration"] >= 0, f"Expected duration ≥ 0, got: {result['duration']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])