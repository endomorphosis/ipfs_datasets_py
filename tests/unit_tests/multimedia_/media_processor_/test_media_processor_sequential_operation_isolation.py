#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for MediaProcessor operation isolation and sequential execution.

This module tests MediaProcessor's handling of multiple operations,
focusing on error isolation and sequential operation behavior that can
be verified through the public API.

SHARED DEFINITIONS:
==================

Test Parameters:
- Sequential operations: Individual calls to download_and_convert()
- Error isolation: Failed operations do not affect subsequent operations
- Operation independence: Each operation maintains its own state and results

Error Handling:
- Graceful failure: Operations return error status without raising exceptions
- State consistency: MediaProcessor remains functional after operation failures
- Result isolation: One operation's failure does not corrupt another's results
"""

import pytest
import os
import asyncio
import time
from unittest.mock import Mock, patch, MagicMock

# Make sure the input file and documentation file exist.
work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/multimedia/media_processor.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/multimedia/media_processor_stubs.md")

# Import the MediaProcessor class and its class dependencies
from ipfs_datasets_py.multimedia.media_processor import MediaProcessor, make_media_processor
from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

# No test-specific constants needed - using fixtures


class TestConcurrentOperationScaling:
    """
    Test error isolation and sequential operation handling.
    
    This test class validates MediaProcessor's ability to handle multiple operations
    and maintain isolation between operations when errors occur. Tests focus on
    externally observable behaviors through the public API.
    
    Production method tested: MediaProcessor.download_and_convert()
    
    Shared terminology:
    - Operation isolation: Failed operations do not affect subsequent operations
    - Sequential execution: Operations executed one after another
    - Error recovery: System remains functional after operation failures
    """

    @pytest.mark.asyncio
    async def test_when_multiple_downloads_executed_then_operations_complete_successfully(self, mock_processor, test_url):
        """
        Test multiple sequential download operations complete successfully.
        
        GIVEN: A MediaProcessor and multiple download URLs
        WHEN: Multiple download_and_convert operations are executed sequentially
        THEN: All operations return success status
        """
        # Arrange
        urls = [f"{test_url}_{i}" for i in range(3)]
        expected_status = "success"
        
        # Act
        results = []
        for url in urls:
            result = await mock_processor.download_and_convert(url)
            results.append(result)
        
        # Assert
        assert all(result["status"] == expected_status for result in results), f"Expected all operations to return status '{expected_status}', but got statuses: {[r['status'] for r in results]}"

    @pytest.mark.asyncio
    async def test_when_download_fails_then_other_operations_unaffected(self, tmp_path, test_url, mock_factory):
        """
        Test error in one operation does not affect subsequent operations.
        
        GIVEN: A MediaProcessor where first operation fails and second succeeds
        WHEN: Two download_and_convert operations are executed sequentially  
        THEN: Second operation returns success status despite first operation failure
        """
        # Arrange
        processor = mock_factory.create_mock_processor(tmp_path)
        failing_url = f"{test_url}_failing"
        successful_url = f"{test_url}_success"
        expected_first_status = "error"
        expected_second_status = "success"
        
        # Mock the ytdlp wrapper to fail on first URL but succeed on second
        with patch.object(processor.ytdlp, 'download_video') as mock_download:
            mock_download.side_effect = [
                Exception("Download failed"), 
                {
                    "status": "success",
                    "output_path": str(tmp_path / "success_video.mp4"),
                    "title": "Success Video",
                    "duration": 120,
                    "filesize": 1048576,
                    "format": "mp4"
                }
            ]
            
            # Act
            first_result = await processor.download_and_convert(failing_url)
            second_result = await processor.download_and_convert(successful_url)
        
        # Assert
        assert first_result["status"] == expected_first_status, f"Expected first operation to return status '{expected_first_status}', but got '{first_result['status']}'"
        assert second_result["status"] == expected_second_status, f"Expected second operation to return status '{expected_second_status}', but got '{second_result['status']}'"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
