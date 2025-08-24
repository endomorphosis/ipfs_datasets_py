#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test MediaProcessor cleanup completion rate for temporary file management.

This module tests the MediaProcessor's download_and_convert method and get_capabilities method
for proper cleanup behavior and success/failure response handling.

Terms:
- cleanup completion rate: The percentage of temporary files that are successfully removed after operations
- successful operation: Operation that returns status 'success' with expected output fields
- failed operation: Operation that returns status 'error' with error details
"""

import pytest

# Test data constants  
DEFAULT_URL = "https://example.com/video"
DEFAULT_OUTPUT_FORMAT = "mp4"
DEFAULT_QUALITY = "720p"
EXPECTED_SUCCESS_STATUS = "success"
EXPECTED_ERROR_STATUS = "error"
EXPECTED_WEBM_FORMAT = "webm"


class TestDownloadAndConvertSuccessfulOperations:
    """
    Test successful download_and_convert operations for MediaProcessor.
    
    Covers successful operation response structure and metadata fields.
    """

    @pytest.mark.asyncio
    async def test_when_successful_operation_then_returns_success_status(self, default_processor):
        """
        GIVEN MediaProcessor with successful configuration
        WHEN download_and_convert is called with valid parameters
        THEN returns dictionary with status 'success'
        """
        result = await default_processor.download_and_convert(
            url=DEFAULT_URL,
            output_format=DEFAULT_OUTPUT_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert result["status"] == EXPECTED_SUCCESS_STATUS, f"Expected status '{EXPECTED_SUCCESS_STATUS}', got '{result['status']}'"

    @pytest.mark.asyncio
    async def test_when_successful_operation_then_includes_output_path(self, successful_processor):
        """
        GIVEN MediaProcessor with successful configuration
        WHEN download_and_convert completes successfully
        THEN result includes non-empty output_path string
        """
        result = await successful_processor.download_and_convert(
            url=DEFAULT_URL,
            output_format=DEFAULT_OUTPUT_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert isinstance(result["output_path"], str), f"Expected output_path to be str, got {type(result['output_path'])}"

    @pytest.mark.asyncio
    async def test_when_successful_operation_then_includes_title_metadata(self, processor_with_title, test_video_title):
        """
        GIVEN MediaProcessor configured to return video metadata
        WHEN download_and_convert completes successfully
        THEN result includes title field with expected value
        """
        result = await processor_with_title.download_and_convert(
            url=DEFAULT_URL,
            output_format=DEFAULT_OUTPUT_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert result["title"] == test_video_title, f"Expected title '{test_video_title}', got '{result['title']}'"

    @pytest.mark.asyncio
    async def test_when_successful_operation_then_includes_duration_metadata(self, processor_with_duration, test_video_duration):
        """
        GIVEN MediaProcessor configured to return video metadata
        WHEN download_and_convert completes successfully
        THEN result includes duration field with expected numeric value
        """
        result = await processor_with_duration.download_and_convert(
            url=DEFAULT_URL,
            output_format=DEFAULT_OUTPUT_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert result["duration"] == test_video_duration, f"Expected duration {test_video_duration}, got {result['duration']}"

    @pytest.mark.asyncio
    async def test_when_successful_operation_then_includes_filesize_metadata(self, processor_with_filesize, test_file_size):
        """
        GIVEN MediaProcessor configured to return file metadata
        WHEN download_and_convert completes successfully
        THEN result includes filesize field with expected integer value
        """
        result = await processor_with_filesize.download_and_convert(
            url=DEFAULT_URL,
            output_format=DEFAULT_OUTPUT_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert result["filesize"] == test_file_size, f"Expected filesize {test_file_size}, got {result['filesize']}"

    @pytest.mark.asyncio
    async def test_when_conversion_occurs_then_includes_converted_path(self, conversion_processor):
        """
        GIVEN MediaProcessor configured for format conversion
        WHEN download_and_convert converts to different format
        THEN result includes converted_path field with webm extension
        """
        result = await conversion_processor.download_and_convert(
            url=DEFAULT_URL,
            output_format=EXPECTED_WEBM_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert result["converted_path"].endswith(f"video.{EXPECTED_WEBM_FORMAT}"), f"Expected converted_path to end with 'video.{EXPECTED_WEBM_FORMAT}', got '{result['converted_path']}'"


class TestDownloadAndConvertFailedOperations:
    """
    Test failed download_and_convert operations for MediaProcessor.
    
    Covers error handling for download failures and conversion failures.
    """

    @pytest.mark.asyncio
    async def test_when_download_fails_then_returns_error_status(self, download_failure_processor):
        """
        GIVEN MediaProcessor configured to fail during download
        WHEN download_and_convert encounters download error
        THEN returns dictionary with status 'error'
        """
        result = await download_failure_processor.download_and_convert(
            url=DEFAULT_URL,
            output_format=DEFAULT_OUTPUT_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert result["status"] == EXPECTED_ERROR_STATUS, f"Expected status '{EXPECTED_ERROR_STATUS}', got '{result['status']}'"

    @pytest.mark.asyncio
    async def test_when_download_fails_then_includes_error_message(self, download_failure_processor):
        """
        GIVEN MediaProcessor configured to fail during download
        WHEN download_and_convert encounters download error
        THEN result includes non-empty error message string
        """
        result = await download_failure_processor.download_and_convert(
            url=DEFAULT_URL,
            output_format=DEFAULT_OUTPUT_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert isinstance(result["error"], str), f"Expected error to be str, got {type(result['error'])}"

    @pytest.mark.asyncio
    async def test_when_conversion_fails_then_returns_error_status(self, conversion_failure_processor):
        """
        GIVEN MediaProcessor configured to fail during conversion
        WHEN download_and_convert encounters conversion error
        THEN returns dictionary with status 'error'
        """
        result = await conversion_failure_processor.download_and_convert(
            url=DEFAULT_URL,
            output_format=EXPECTED_WEBM_FORMAT,
            quality=DEFAULT_QUALITY
        )
        
        assert result["status"] == EXPECTED_ERROR_STATUS, f"Expected status '{EXPECTED_ERROR_STATUS}', got '{result['status']}'"


class TestGetCapabilitiesMethod:
    """
    Test get_capabilities method for MediaProcessor.
    
    Covers capabilities reporting and supported operations.
    """

    def test_when_get_capabilities_called_then_returns_supported_operations(self, mock_capabilities_processor, test_expected_capabilities):
        """
        GIVEN MediaProcessor instance
        WHEN get_capabilities is called
        THEN returns dictionary containing expected supported operations
        """
        capabilities = mock_capabilities_processor.get_capabilities()
        
        for capability in capabilities.keys():
            assert capability in test_expected_capabilities, f"Unexpected capability '{capability}' not in expected list {test_expected_capabilities}"


class TestProcessorConfiguration:
    """
    Test MediaProcessor configuration and attributes.
    
    Covers processor initialization and dependency injection.
    """

    def test_when_processor_created_with_logging_then_enable_logging_is_true(self, default_processor_with_logging):
        """
        GIVEN MediaProcessor created with enable_logging=True
        WHEN accessing enable_logging attribute
        THEN attribute value equals True
        """
        assert default_processor_with_logging.enable_logging == True, f"Expected enable_logging to be True, got {default_processor_with_logging.enable_logging}"

    def test_when_processor_created_with_ytdlp_then_ytdlp_attribute_set(self, processor_with_mock_ytdlp):
        """
        GIVEN MediaProcessor created with ytdlp dependency
        WHEN accessing ytdlp attribute
        THEN attribute contains expected YtDlpWrapper instance
        """
        processor, mock_ytdlp = processor_with_mock_ytdlp
        
        assert processor.ytdlp is mock_ytdlp, f"Expected ytdlp to be {mock_ytdlp}, got {processor.ytdlp}"

    def test_when_processor_created_with_ffmpeg_then_ffmpeg_attribute_set(self, processor_with_mock_ffmpeg):
        """
        GIVEN MediaProcessor created with ffmpeg dependency
        WHEN accessing ffmpeg attribute
        THEN attribute contains expected FFmpegWrapper instance
        """
        processor, mock_ffmpeg = processor_with_mock_ffmpeg
        
        assert processor.ffmpeg is mock_ffmpeg, f"Expected ffmpeg to be {mock_ffmpeg}, got {processor.ffmpeg}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])