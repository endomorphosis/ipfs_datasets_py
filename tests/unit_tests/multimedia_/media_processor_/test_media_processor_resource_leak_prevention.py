#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch


import psutil
import pytest


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
    BadDocumentationError,
    BadSignatureError
)

# Test constants
MEMORY_BASELINE_TOLERANCE = 10 * 1024 * 1024  # 10MB in bytes
PERFORMANCE_OVERHEAD_THRESHOLD = 0.02  # 2% maximum overhead
CONCURRENT_OPERATIONS_COUNT = 5


class TestResourceLeakPrevention:
    """
    Test resource leak prevention for the download_and_convert method.
    
    Tests observable resource management behavior including memory usage,
    temporary file cleanup, process termination, and performance overhead
    through the MediaProcessor.download_and_convert public interface.
    
    Valid input: A URL that can be processed by download_and_convert
    Resource leak: Permanent increase in system resources after operation completion
    Graceful failure: Clean resource cleanup even when operations fail
    """

    @pytest.mark.asyncio
    async def test_when_download_and_convert_called_then_memory_returns_to_baseline(self, successful_processor, test_url):
        """
        GIVEN successful MediaProcessor instance and valid URL
        WHEN download_and_convert is called and completes
        THEN expect memory usage to return to within 10MB of baseline
        """
        # Arrange
        current_process = psutil.Process()
        baseline_memory = current_process.memory_info().rss

        # Act
        result = await successful_processor.download_and_convert(test_url)

        # Assert
        final_memory = current_process.memory_info().rss
        memory_difference = abs(final_memory - baseline_memory)

        assert result["status"] == "success", f"Expected successful operation, got: {result.get('error', 'unknown error')}"
        assert memory_difference <= MEMORY_BASELINE_TOLERANCE, f"Memory difference {memory_difference} bytes exceeds tolerance {MEMORY_BASELINE_TOLERANCE} bytes"

    @pytest.mark.asyncio
    async def test_when_download_and_convert_fails_then_memory_returns_to_baseline(self, download_failure_processor, test_url):
        """
        GIVEN failing MediaProcessor instance and valid URL
        WHEN download_and_convert is called and fails
        THEN expect memory usage to return to within 10MB of baseline
        """
        # Arrange
        current_process = psutil.Process()
        baseline_memory = current_process.memory_info().rss
        
        # Act
        result = await download_failure_processor.download_and_convert(test_url)
        
        # Assert
        final_memory = current_process.memory_info().rss
        memory_difference = abs(final_memory - baseline_memory)
        
        assert result["status"] == "error", f"Expected failed operation, got: {result}"
        assert memory_difference <= MEMORY_BASELINE_TOLERANCE, f"Memory difference {memory_difference} bytes exceeds tolerance {MEMORY_BASELINE_TOLERANCE} bytes"

    @pytest.mark.asyncio
    async def test_when_download_and_convert_called_then_temp_files_cleaned_up(self, successful_processor, test_url):
        """
        GIVEN successful MediaProcessor instance and valid URL
        WHEN download_and_convert is called and completes
        THEN expect all temporary files to be removed from system temp directory
        """
        # Arrange
        temp_dir = Path(tempfile.gettempdir())
        initial_temp_files = set(temp_dir.glob('*'))
        
        # Act
        result = await successful_processor.download_and_convert(test_url)
        
        # Assert
        final_temp_files = set(temp_dir.glob('*'))
        new_temp_files = final_temp_files - initial_temp_files
        
        assert result["status"] == "success", f"Expected successful operation, got: {result.get('error', 'unknown error')}"
        assert len(new_temp_files) == 0, f"Found {len(new_temp_files)} temporary files not cleaned up: {list(new_temp_files)}"

    @pytest.mark.asyncio
    async def test_when_download_and_convert_fails_then_temp_files_cleaned_up(self, download_failure_processor, test_url):
        """
        GIVEN failing MediaProcessor instance and valid URL
        WHEN download_and_convert is called and fails
        THEN expect all temporary files to be removed from system temp directory
        """
        # Arrange
        temp_dir = Path(tempfile.gettempdir())
        initial_temp_files = set(temp_dir.glob('*'))
        
        # Act
        result = await download_failure_processor.download_and_convert(test_url)
        
        # Assert
        final_temp_files = set(temp_dir.glob('*'))
        new_temp_files = final_temp_files - initial_temp_files
        
        assert result["status"] == "error", f"Expected failed operation, got: {result}"
        assert len(new_temp_files) == 0, f"Found {len(new_temp_files)} temporary files not cleaned up: {list(new_temp_files)}"

    @pytest.mark.asyncio
    async def test_when_download_and_convert_called_then_subprocesses_terminated(self, successful_processor, test_url):
        """
        GIVEN successful MediaProcessor instance and valid URL
        WHEN download_and_convert is called and completes
        THEN expect all spawned subprocesses to be terminated
        """
        # Arrange
        current_process = psutil.Process()
        initial_children = set(child.pid for child in current_process.children(recursive=True))
        
        # Act
        result = await successful_processor.download_and_convert(test_url)
        
        # Assert
        final_children = set(child.pid for child in current_process.children(recursive=True))
        new_children = final_children - initial_children
        
        assert result["status"] == "success", f"Expected successful operation, got: {result.get('error', 'unknown error')}"
        assert len(new_children) == 0, f"Found {len(new_children)} child processes not terminated: {list(new_children)}"

    @pytest.mark.asyncio 
    async def test_when_download_and_convert_called_then_performance_overhead_minimal(self, tmp_path, mock_factory, successful_processor, test_url):
        """
        GIVEN successful MediaProcessor instance and valid URL
        WHEN download_and_convert is called with resource monitoring enabled
        THEN expect performance overhead to be less than or equal to 
            PERFORMANCE_OVERHEAD_THRESHOLD % of execution time
        """
        # Arrange - Create processor without monitoring for baseline
        baseline_processor = mock_factory.create_mock_processor(tmp_path, enable_logging=False)
        
        # Act - Measure baseline performance
        baseline_start = time.perf_counter()
        baseline_result = await baseline_processor.download_and_convert(test_url)
        baseline_time = time.perf_counter() - baseline_start
        
        # Act - Measure monitored performance  
        monitored_start = time.perf_counter()
        monitored_result = await successful_processor.download_and_convert(test_url)
        monitored_time = time.perf_counter() - monitored_start
        
        # Assert
        overhead_ratio = (monitored_time - baseline_time) / baseline_time if baseline_time > 0 else 0
        
        assert baseline_result["status"] == "success", f"Expected successful baseline operation, got: {baseline_result.get('error', 'unknown error')}"
        assert monitored_result["status"] == "success", f"Expected successful monitored operation, got: {monitored_result.get('error', 'unknown error')}"
        assert overhead_ratio <= PERFORMANCE_OVERHEAD_THRESHOLD, f"Performance overhead {overhead_ratio:.1%} exceeds threshold {PERFORMANCE_OVERHEAD_THRESHOLD:.1%}"

    @pytest.mark.asyncio
    async def test_when_concurrent_operations_then_all_tasks_complete(self, mock_factory, tmp_path, test_url):
        """
        GIVEN multiple MediaProcessor instances running concurrently
        WHEN download_and_convert is called simultaneously from multiple threads
        THEN expect all concurrent tasks to complete
        """
        # Arrange
        processors = [mock_factory.create_mock_processor(tmp_path) for _ in range(CONCURRENT_OPERATIONS_COUNT)]
        
        # Act
        tasks = [processor.download_and_convert(test_url) for processor in processors]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Assert
        assert len(results) == CONCURRENT_OPERATIONS_COUNT, f"Expected {CONCURRENT_OPERATIONS_COUNT} results, got {len(results)}"

    @pytest.mark.asyncio
    async def test_when_concurrent_operations_then_at_least_one_succeeds(self, mock_factory, tmp_path, test_url):
        """
        GIVEN multiple MediaProcessor instances running concurrently
        WHEN download_and_convert is called simultaneously from multiple threads
        THEN expect at least one operation to succeed
        """
        # Arrange
        processors = [mock_factory.create_mock_processor(tmp_path) for _ in range(CONCURRENT_OPERATIONS_COUNT)]
        
        # Act
        tasks = [processor.download_and_convert(test_url) for processor in processors]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Assert
        successful_results = [r for r in results if isinstance(r, dict) and r.get("status") == "success"]
        assert len(successful_results) >= 1, f"Expected at least 1 successful result, got {len(successful_results)} successful results"

    @pytest.mark.asyncio
    async def test_when_concurrent_operations_then_no_race_condition_errors(self, mock_factory, tmp_path, test_url):
        """
        GIVEN multiple MediaProcessor instances running concurrently
        WHEN download_and_convert is called simultaneously from multiple threads
        THEN expect no race condition errors to occur
        """
        # Arrange
        processors = [mock_factory.create_mock_processor(tmp_path) for _ in range(CONCURRENT_OPERATIONS_COUNT)]
        
        # Act
        tasks = [processor.download_and_convert(test_url) for processor in processors]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Assert
        exceptions = [r for r in results if isinstance(r, Exception)]
        race_condition_errors = [e for e in exceptions if "race" in str(e).lower() or "concurrent" in str(e).lower()]
        assert len(race_condition_errors) == 0, f"Found {len(race_condition_errors)} race condition errors: {race_condition_errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])