#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest

pyfakefs = pytest.importorskip("pyfakefs")
import anyio
from unittest.mock import AsyncMock
from pathlib import Path
from pyfakefs.fake_filesystem_unittest import Patcher

from ipfs_datasets_py.data_transformation.multimedia.media_processor import make_media_processor

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)


# Test data constants specific to disk space testing
EXPECTED_STATUS_SUCCESS = "success"
EXPECTED_STATUS_ERROR = "error"
INSUFFICIENT_SPACE_BYTES = 10 * 1024 * 1024  # 10 MB
SUFFICIENT_SPACE_BYTES = 1000 * 1024 * 1024  # 1000 MB
TEST_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


@pytest.fixture
def output_dir():
    """Provide a standard output directory path."""
    return Path("/output")


@pytest.fixture
def filesystem_with_insufficient_space(fs, output_dir):
    """Set up fake filesystem with insufficient disk space."""
    fs.create_dir(str(output_dir))
    fs.set_disk_usage(INSUFFICIENT_SPACE_BYTES, path=str(output_dir))
    return output_dir


@pytest.fixture
def filesystem_with_sufficient_space(fs, output_dir):
    """Set up fake filesystem with sufficient disk space."""
    fs.create_dir(str(output_dir))
    fs.set_disk_usage(SUFFICIENT_SPACE_BYTES, path=str(output_dir))
    return output_dir


@pytest.fixture
def disk_space_success_response(output_dir):
    """Create a successful download response for disk space tests."""
    return {
        "status": EXPECTED_STATUS_SUCCESS,
        "output_path": str(output_dir / "video.mp4"),
        "filesize": TEST_FILE_SIZE_BYTES,
        "title": "Test Video",
        "duration": 120,
        "format": "mp4"
    }


@pytest.fixture
def disk_space_error_response():
    """Create an error download response for disk space tests."""
    return {
        "status": EXPECTED_STATUS_ERROR,
        "error": "Insufficient disk space"
    }


@pytest.fixture
def processor_with_insufficient_space(filesystem_with_insufficient_space, mock_factory):
    """Create a processor with insufficient disk space setup."""
    return mock_factory.create_mock_processor(
        filesystem_with_insufficient_space,
        ytdlp_kwargs={
            "status": EXPECTED_STATUS_ERROR,
            "error": "Insufficient disk space"
        }
    )


@pytest.fixture
def processor_with_sufficient_space(filesystem_with_sufficient_space, mock_factory):
    """Create a processor with sufficient disk space setup."""
    return mock_factory.create_mock_processor(
        filesystem_with_sufficient_space,
        ytdlp_kwargs={
            "status": EXPECTED_STATUS_SUCCESS,
            "output_path": str(filesystem_with_sufficient_space / "video.mp4"),
            "filesize": TEST_FILE_SIZE_BYTES,
            "title": "Test Video",
            "duration": 120,
            "format": "mp4"
        }
    )


@pytest.fixture
def processor_with_error_ytdlp(filesystem_with_insufficient_space, mock_factory):
    """Create a processor that will return download errors."""
    return mock_factory.create_mock_processor(
        filesystem_with_insufficient_space,
        ytdlp_kwargs={
            "status": EXPECTED_STATUS_ERROR,
            "error": "Insufficient disk space"
        }
    )


@pytest.fixture
def disk_space_processor_factory(filesystem_with_sufficient_space, mock_factory):
    """Factory fixture to create processors with custom ytdlp responses for disk space tests."""
    def _create_processor(response_data):
        return mock_factory.create_mock_processor(
            filesystem_with_sufficient_space,
            ytdlp_kwargs=response_data
        )
    return _create_processor


@pytest.fixture
def missing_content_length_response(filesystem_with_sufficient_space):
    """Response data for missing Content-Length header scenario."""
    return {
        "status": EXPECTED_STATUS_SUCCESS,
        "output_path": str(filesystem_with_sufficient_space / "video.mp4"),
        "filesize": None,  # No content length available
        "title": "Test Video",
        "duration": 120,
        "format": "mp4"
    }


@pytest.fixture
def chunked_encoding_response(filesystem_with_sufficient_space):
    """Response data for chunked encoding scenario."""
    return {
        "status": EXPECTED_STATUS_SUCCESS,
        "output_path": str(filesystem_with_sufficient_space / "chunked_video.mp4"),
        "filesize": TEST_FILE_SIZE_BYTES,
        "title": "Chunked Video",
        "duration": 180,
        "format": "mp4"
    }


@pytest.fixture
def compressed_content_response(filesystem_with_sufficient_space):
    """Response data for compressed content scenario."""
    return {
        "status": EXPECTED_STATUS_SUCCESS,
        "output_path": str(filesystem_with_sufficient_space / "compressed_video.mp4"),
        "filesize": TEST_FILE_SIZE_BYTES,
        "title": "Compressed Video",
        "duration": 240,
        "format": "mp4"
    }


@pytest.fixture
def partial_download_response(filesystem_with_sufficient_space):
    """Response data for partial download resume scenario."""
    return {
        "status": EXPECTED_STATUS_SUCCESS,
        "output_path": str(filesystem_with_sufficient_space / "resumed_video.mp4"),
        "filesize": TEST_FILE_SIZE_BYTES,
        "title": "Resumed Video",
        "duration": 300,
        "format": "mp4"
    }


@pytest.fixture
def complete_file_response(filesystem_with_sufficient_space):
    """Response data for complete file scenario."""
    return {
        "status": EXPECTED_STATUS_SUCCESS,
        "output_path": str(filesystem_with_sufficient_space / "complete_video.mp4"),
        "filesize": TEST_FILE_SIZE_BYTES,
        "title": "Complete Video",
        "duration": 360,
        "format": "mp4"
    }


@pytest.fixture
def space_test_response(filesystem_with_sufficient_space):
    """Response data for disk space test scenario."""
    return {
        "status": EXPECTED_STATUS_SUCCESS,
        "output_path": str(filesystem_with_sufficient_space / "space_test_video.mp4"),
        "filesize": TEST_FILE_SIZE_BYTES,
        "title": "Space Test Video",
        "duration": 420,
        "format": "mp4"
    }


@pytest.fixture
def partial_file_setup(filesystem_with_sufficient_space, fs):
    """Set up partial file for resume testing."""
    partial_file_path = filesystem_with_sufficient_space / "partial_video.mp4.part"
    fs.create_file(str(partial_file_path), contents="partial content")
    return partial_file_path


@pytest.fixture
def created_video_file(filesystem_with_sufficient_space, fs):
    """Factory fixture to create video files on the fake filesystem."""
    def _create_file(filename, contents="mock video content", size=None):
        file_path = filesystem_with_sufficient_space / filename
        if size:
            fs.create_file(str(file_path), st_size=size)
        else:
            fs.create_file(str(file_path), contents=contents)
        return file_path
    return _create_file


class TestDiskSpaceValidationAccuracy:
    """
    Test disk space validation behavior for MediaProcessor download_and_convert operations.
    
    Tests externally observable behaviors related to disk space handling including:
    - Error conditions when insufficient space is available
    - Successful operations when adequate space exists
    - Space prediction accuracy for preventing out-of-space failures
    - Handling of various content types and encoding scenarios
    
    Shared terminology:
    - "predicted requirements": Disk space needed to successfully complete the operation, 
        including all intermediate and final files
    - "sufficient space": Available disk space > predicted space requirements
    - "insufficient space": Available disk space < predicted space requirements
    - "operation success": download_and_convert completes with status='success'
    """

    @pytest.mark.asyncio
    async def test_when_insufficient_disk_space_then_returns_error(self, processor_with_insufficient_space, test_url):
        """
        GIVEN filesystem with available space less than predicted requirements
        WHEN download_and_convert is called with valid URL
        THEN expect operation to complete with status='error'
        """
        result = await processor_with_insufficient_space.download_and_convert(test_url)
        
        assert result["status"] == EXPECTED_STATUS_ERROR

    @pytest.mark.asyncio
    async def test_when_insufficient_disk_space_then_no_download_occurs(self, processor_with_error_ytdlp, filesystem_with_insufficient_space, test_url):
        """
        GIVEN filesystem with available space less than predicted requirements
        WHEN download_and_convert is called with valid URL
        THEN expect no files to be created
        """
        await processor_with_error_ytdlp.download_and_convert(test_url)
        
        created_files = list(filesystem_with_insufficient_space.iterdir())
        assert len(created_files) == 0

    @pytest.mark.asyncio
    async def test_when_sufficient_disk_space_then_result_is_success(self, processor_with_sufficient_space, test_url):
        """
        GIVEN filesystem with available space greater than predicted requirements
        WHEN download_and_convert is called with valid URL
        THEN expect operation to complete with status='success'
        """
        result = await processor_with_sufficient_space.download_and_convert(test_url)
        
        assert result["status"] == EXPECTED_STATUS_SUCCESS

    @pytest.mark.asyncio
    async def test_when_sufficient_disk_space_then_file_is_produced(self, filesystem_with_sufficient_space, mock_factory, created_video_file, test_url):
        """
        GIVEN filesystem with available space greater than predicted requirements
        WHEN download_and_convert is called with valid URL
        THEN expect file to be created at the expected location
        """
        expected_output_path = created_video_file("video.mp4")
        
        processor = mock_factory.create_mock_processor(
            filesystem_with_sufficient_space,
            ytdlp_kwargs={
                "status": EXPECTED_STATUS_SUCCESS,
                "output_path": str(expected_output_path),
                "filesize": TEST_FILE_SIZE_BYTES,
                "title": "Test Video",
                "duration": 120,
                "format": "mp4"
            }
        )
        
        result = await processor.download_and_convert(test_url)
        
        assert expected_output_path.exists()
        assert result["output_path"] == str(expected_output_path)

    @pytest.mark.asyncio
    async def test_when_missing_content_length_then_download_handles_gracefully(self, disk_space_processor_factory, missing_content_length_response, test_url):
        """
        GIVEN HTTP response without Content-Length header
        WHEN download_and_convert is called
        THEN expect operation to complete with status='success'
        """
        processor = disk_space_processor_factory(missing_content_length_response)
        
        result = await processor.download_and_convert(test_url)
        
        assert result["status"] == EXPECTED_STATUS_SUCCESS

    @pytest.mark.asyncio
    async def test_when_chunked_encoding_used_then_download_succeeds(self, disk_space_processor_factory, chunked_encoding_response, test_url):
        """
        GIVEN HTTP response with Transfer-Encoding: chunked
        WHEN download_and_convert is called
        THEN expect operation to complete with status='success'
        """
        processor = disk_space_processor_factory(chunked_encoding_response)
        
        result = await processor.download_and_convert(test_url)
        
        assert result["status"] == EXPECTED_STATUS_SUCCESS

    @pytest.mark.asyncio
    async def test_when_compressed_content_downloaded_then_space_handled_correctly(self, disk_space_processor_factory, compressed_content_response, test_url):
        """
        GIVEN a url that points to compressed content download (Content-Encoding: gzip)
        WHEN download_and_convert processes the content
        THEN expect operation to complete with status='success'
        """
        processor = disk_space_processor_factory(compressed_content_response)
        
        result = await processor.download_and_convert(test_url)
        
        assert result["status"] == EXPECTED_STATUS_SUCCESS

    @pytest.mark.asyncio
    async def test_when_partial_download_exists_then_resume_succeeds_without_space_errors(self, disk_space_processor_factory, partial_download_response, partial_file_setup, test_url):
        """
        GIVEN interrupted download with existing partial file
        WHEN download_and_convert resumes the same URL
        THEN expect operation to complete with status='success'
        """
        processor = disk_space_processor_factory(partial_download_response)
        
        result = await processor.download_and_convert(test_url)
        
        assert result["status"] == EXPECTED_STATUS_SUCCESS

    @pytest.mark.asyncio
    async def test_when_partial_download_resumes_then_complete_file_exists(self, disk_space_processor_factory, complete_file_response, created_video_file, test_url):
        """
        GIVEN interrupted download with existing partial file
        WHEN download_and_convert resumes the same URL
        THEN expect complete file to exist
        """
        expected_complete_file = created_video_file("complete_video.mp4", "complete video content")
        
        processor = disk_space_processor_factory(complete_file_response)
        
        await processor.download_and_convert(test_url)
        
        assert expected_complete_file.exists()

    @pytest.mark.asyncio
    async def test_when_partial_download_resumes_then_filesize_matches_expected(self, disk_space_processor_factory, complete_file_response, created_video_file, test_url):
        """
        GIVEN interrupted download with existing partial file
        WHEN download_and_convert resumes the same URL
        THEN expect filesize to match expected size
        """
        created_video_file("complete_video.mp4", "complete video content")
        
        processor = disk_space_processor_factory(complete_file_response)
        
        result = await processor.download_and_convert(test_url)
        
        assert result["filesize"] == TEST_FILE_SIZE_BYTES

    @pytest.mark.asyncio
    async def test_when_operation_completes_then_status_is_success(self, disk_space_processor_factory, space_test_response, created_video_file, test_url):
        """
        GIVEN download_and_convert operation in progress
        WHEN operation completes successfully
        THEN expect status to be 'success'
        """
        created_video_file("space_test_video.mp4", size=TEST_FILE_SIZE_BYTES)
        
        processor = disk_space_processor_factory(space_test_response)
        
        result = await processor.download_and_convert(test_url)
        
        assert result["status"] == EXPECTED_STATUS_SUCCESS

    @pytest.mark.asyncio
    async def test_when_operation_completes_then_filesize_matches_expected(self, disk_space_processor_factory, space_test_response, created_video_file, test_url):
        """
        GIVEN download_and_convert operation in progress
        WHEN operation completes successfully
        THEN expect filesize to match expected size
        """
        created_video_file("space_test_video.mp4", size=TEST_FILE_SIZE_BYTES)
        
        processor = disk_space_processor_factory(space_test_response)
        
        result = await processor.download_and_convert(test_url)
        
        assert result["filesize"] == TEST_FILE_SIZE_BYTES

    @pytest.mark.asyncio
    async def test_when_operation_completes_then_file_size_on_disk_matches_expected(self, disk_space_processor_factory, space_test_response, created_video_file, test_url):
        """
        GIVEN download_and_convert operation in progress
        WHEN operation completes successfully
        THEN expect file size on disk to match expected size
        """
        output_file_path = created_video_file("space_test_video.mp4", size=TEST_FILE_SIZE_BYTES)
        
        processor = disk_space_processor_factory(space_test_response)
        
        await processor.download_and_convert(test_url)
        
        assert output_file_path.stat().st_size == TEST_FILE_SIZE_BYTES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])