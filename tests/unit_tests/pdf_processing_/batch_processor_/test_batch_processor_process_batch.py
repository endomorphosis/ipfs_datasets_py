# Test file for TestBatchProcessorProcessBatch class
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/batch_processor.py
# Auto-generated on 2025-07-07 02:28:57"

import pytest
import os

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/batch_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/batch_processor_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

import pytest
import json
import csv
import os
import tempfile
import time
import asyncio
import threading
import multiprocessing
from pathlib import Path
from queue import Queue
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import Mock, patch, AsyncMock

from ipfs_datasets_py.pdf_processing.batch_processor import (
    process_directory_batch,
    BatchProcessor,
    ProcessingJob,
    BatchJobResult,
    BatchStatus
)

import pytest
from datetime import datetime
from ipfs_datasets_py.pdf_processing.batch_processor import (
    ProcessingJob, BatchJobResult, BatchStatus
)


from ipfs_datasets_py.ipld.storage import IPLDStorage

# Check if each classes methods are accessible:
assert IPLDStorage

assert BatchProcessor.process_batch
assert BatchProcessor._start_workers
assert BatchProcessor._worker_loop
assert BatchProcessor._process_single_job
assert BatchProcessor._update_batch_status
assert BatchProcessor._monitor_batch_progress
assert BatchProcessor.get_batch_status
assert BatchProcessor.list_active_batches
assert BatchProcessor.cancel_batch
assert BatchProcessor.stop_processing
assert BatchProcessor._get_resource_usage
assert BatchProcessor.get_processing_statistics
assert BatchProcessor.export_batch_results


class TestBatchProcessorProcessBatch:
    """Test class for process_batch method in BatchProcessor."""

    @pytest.fixture
    def processor(self):
        """Create a BatchProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(max_workers=4, max_memory_mb=2048)
            processor._start_workers = AsyncMock()
            processor._monitor_batch_progress = AsyncMock()
            return processor

    @pytest.fixture
    def sample_pdf_files(self):
        """Create temporary PDF files for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_paths = []
            for i in range(3):
                pdf_path = Path(temp_dir) / f"document_{i}.pdf"
                pdf_path.write_text(f"Mock PDF content {i}")
                pdf_paths.append(str(pdf_path))
            yield pdf_paths

    @pytest.mark.asyncio
    async def test_process_batch_basic_functionality(self, processor, sample_pdf_files):
        """
        GIVEN a list of valid PDF file paths
        WHEN process_batch is called with default parameters
        THEN it should:
         - Generate a unique batch ID in format 'batch_{8_char_hex}'
         - Create ProcessingJob instances for each PDF
         - Add jobs to the job queue with correct priority
         - Start worker threads if not already running
         - Create BatchStatus entry in active_batches
         - Return the batch ID for tracking
         - Set up all jobs with pending status initially
        """
        batch_id = await processor.process_batch(pdf_paths=sample_pdf_files)
        
        # Verify batch ID format
        assert batch_id.startswith('batch_')
        assert len(batch_id) == 14  # 'batch_' + 8 hex chars
        
        # Verify batch was created in active_batches
        assert batch_id in processor.active_batches
        batch_status = processor.active_batches[batch_id]
        assert isinstance(batch_status, BatchStatus)
        assert batch_status.total_jobs == 3
        assert batch_status.completed_jobs == 0
        assert batch_status.failed_jobs == 0
        assert batch_status.pending_jobs == 3
        
        # Verify workers were started
        processor._start_workers.assert_called_once()
        
        # Verify jobs were queued
        assert processor.job_queue.qsize() == 3

    @pytest.mark.asyncio
    async def test_process_batch_with_custom_metadata(self, processor, sample_pdf_files):
        """
        GIVEN PDF files and custom batch metadata
        WHEN process_batch is called with batch_metadata parameter
        THEN it should:
         - Include the custom metadata in each ProcessingJob
         - Store metadata in BatchStatus for tracking
         - Preserve all metadata fields throughout processing
         - Make metadata available for audit trails and results
        """
        custom_metadata = {
            'project_id': 'research_2024',
            'user_id': 'scientist_123',
            'description': 'Academic paper analysis',
            'tags': ['research', 'analysis']
        }
        
        batch_id = await processor.process_batch(
            pdf_paths=sample_pdf_files,
            batch_metadata=custom_metadata
        )
        
        # Check that jobs were created with metadata
        jobs_created = []
        while not processor.job_queue.empty():
            job = processor.job_queue.get()
            jobs_created.append(job)
            processor.job_queue.task_done()
        
        assert len(jobs_created) == 3
        for job in jobs_created:
            assert isinstance(job, ProcessingJob)
            assert job.metadata['batch_id'] == batch_id
            assert job.metadata['batch_metadata'] == custom_metadata

    @pytest.mark.asyncio
    async def test_process_batch_with_custom_priority(self, processor, sample_pdf_files):
        """
        GIVEN PDF files and a custom priority level
        WHEN process_batch is called with priority=8
        THEN it should:
         - Set priority=8 for all ProcessingJob instances
         - Use priority for job scheduling decisions
         - Maintain priority throughout job lifecycle
         - Process higher priority jobs before lower priority ones
        """
        batch_id = await processor.process_batch(
            pdf_paths=sample_pdf_files,
            priority=8
        )
        
        # Extract and verify job priorities
        jobs_created = []
        while not processor.job_queue.empty():
            job = processor.job_queue.get()
            jobs_created.append(job)
            processor.job_queue.task_done()
        
        for job in jobs_created:
            assert job.priority == 8

    @pytest.mark.asyncio
    async def test_process_batch_with_progress_callback(self, processor, sample_pdf_files):
        """
        GIVEN PDF files and a progress callback function
        WHEN process_batch is called with callback parameter
        THEN it should:
         - Start monitoring task for progress tracking
         - Call _monitor_batch_progress with batch_id and callback
         - Enable real-time progress updates
         - Handle both sync and async callback functions
        """
        callback_called = False
        
        def progress_callback(status):
            nonlocal callback_called
            callback_called = True
        
        batch_id = await processor.process_batch(
            pdf_paths=sample_pdf_files,
            callback=progress_callback
        )
        
        # Verify monitoring was started
        processor._monitor_batch_progress.assert_called_once_with(batch_id, progress_callback)

    @pytest.mark.asyncio
    async def test_process_batch_with_async_callback(self, processor, sample_pdf_files):
        """
        GIVEN PDF files and an async progress callback function
        WHEN process_batch is called with async callback
        THEN it should:
         - Handle async callback properly in monitoring
         - Start monitoring task with async callback support
         - Not block batch processing on callback execution
        """
        callback_called = False
        
        async def async_progress_callback(status):
            nonlocal callback_called
            callback_called = True
        
        batch_id = await processor.process_batch(
            pdf_paths=sample_pdf_files,
            callback=async_progress_callback
        )
        
        processor._monitor_batch_progress.assert_called_once_with(batch_id, async_progress_callback)

    @pytest.mark.asyncio
    async def test_process_batch_empty_pdf_list(self, processor):
        """
        GIVEN an empty list of PDF paths
        WHEN process_batch is called
        THEN it should:
         - Raise ValueError indicating empty input
         - Not create any jobs or batch entries
         - Not start workers or monitoring
         - Provide clear error message about empty input
        """
        with pytest.raises(ValueError) as exc_info:
            await processor.process_batch(pdf_paths=[])
        
        assert "empty" in str(exc_info.value).lower() or "no files" in str(exc_info.value).lower()
        processor._start_workers.assert_not_called()
        assert len(processor.active_batches) == 0

    @pytest.mark.asyncio
    async def test_process_batch_nonexistent_files(self, processor):
        """
        GIVEN PDF paths that point to non-existent files
        WHEN process_batch is called
        THEN it should:
         - Raise FileNotFoundError for missing files
         - Validate file existence before creating jobs
         - Provide clear error about which files are missing
         - Not create partial batch with some valid files
        """
        nonexistent_files = ["/path/to/missing1.pdf", "/path/to/missing2.pdf"]
        
        with pytest.raises(FileNotFoundError) as exc_info:
            await processor.process_batch(pdf_paths=nonexistent_files)
        
        assert "not found" in str(exc_info.value).lower() or "does not exist" in str(exc_info.value).lower()
        processor._start_workers.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_batch_mixed_valid_invalid_files(self, processor, sample_pdf_files):
        """
        GIVEN a mix of valid and invalid PDF file paths
        WHEN process_batch is called
        THEN it should:
         - Raise FileNotFoundError for any missing files
         - Not process valid files if any are invalid
         - Validate all files before starting any processing
         - Fail fast to prevent partial batch processing
        """
        mixed_files = sample_pdf_files + ["/path/to/missing.pdf"]
        
        with pytest.raises(FileNotFoundError) as exc_info:
            await processor.process_batch(pdf_paths=mixed_files)
        
        processor._start_workers.assert_not_called()
        assert len(processor.active_batches) == 0

    @pytest.mark.asyncio
    async def test_process_batch_invalid_priority_high(self, processor, sample_pdf_files):
        """
        GIVEN a priority value above the valid range (> 10)
        WHEN process_batch is called with priority=15
        THEN it should:
         - Raise ValueError for invalid priority range
         - Indicate valid priority range (1-10)
         - Not create any jobs or start processing
        """
        with pytest.raises(ValueError) as exc_info:
            await processor.process_batch(pdf_paths=sample_pdf_files, priority=15)
        
        assert "priority" in str(exc_info.value).lower()
        assert "1" in str(exc_info.value) and "10" in str(exc_info.value)
        processor._start_workers.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_batch_invalid_priority_low(self, processor, sample_pdf_files):
        """
        GIVEN a priority value below the valid range (< 1)
        WHEN process_batch is called with priority=0
        THEN it should:
         - Raise ValueError for invalid priority range
         - Indicate minimum priority requirement
         - Not create any jobs or start processing
        """
        with pytest.raises(ValueError) as exc_info:
            await processor.process_batch(pdf_paths=sample_pdf_files, priority=0)
        
        assert "priority" in str(exc_info.value).lower()
        processor._start_workers.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_batch_invalid_callback_type(self, processor, sample_pdf_files):
        """
        GIVEN a callback parameter that is not callable
        WHEN process_batch is called with invalid callback
        THEN it should:
         - Raise TypeError indicating callback must be callable
         - Validate callback before starting processing
         - Not create jobs or start workers
        """
        invalid_callback = "not a function"
        
        with pytest.raises(TypeError) as exc_info:
            await processor.process_batch(pdf_paths=sample_pdf_files, callback=invalid_callback)
        
        assert "callable" in str(exc_info.value).lower() or "function" in str(exc_info.value).lower()
        processor._start_workers.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_batch_path_objects_support(self, processor):
        """
        GIVEN PDF paths provided as Path objects instead of strings
        WHEN process_batch is called with Path objects
        THEN it should:
         - Accept Path objects for cross-platform compatibility
         - Convert paths appropriately for processing
         - Create jobs with correct path information
         - Function normally regardless of path type
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path_objects = []
            for i in range(2):
                pdf_path = Path(temp_dir) / f"doc_{i}.pdf"
                pdf_path.write_text(f"content {i}")
                path_objects.append(pdf_path)
            
            batch_id = await processor.process_batch(pdf_paths=path_objects)
            
            assert batch_id.startswith('batch_')
            assert len(processor.active_batches) == 1
            processor._start_workers.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_batch_large_file_list(self, processor):
        """
        GIVEN a large number of PDF files (100+)
        WHEN process_batch is called with the large list
        THEN it should:
         - Handle large batches efficiently
         - Create appropriate number of jobs
         - Maintain reasonable memory usage during job creation
         - Set up batch status with correct job counts
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            large_file_list = []
            for i in range(150):
                pdf_path = Path(temp_dir) / f"large_doc_{i}.pdf"
                pdf_path.write_text(f"content {i}")
                large_file_list.append(str(pdf_path))
            
            batch_id = await processor.process_batch(pdf_paths=large_file_list)
            
            batch_status = processor.active_batches[batch_id]
            assert batch_status.total_jobs == 150
            assert batch_status.pending_jobs == 150
            assert processor.job_queue.qsize() == 150

    @pytest.mark.asyncio
    async def test_process_batch_duplicate_files(self, processor, sample_pdf_files):
        """
        GIVEN PDF paths that contain duplicate file paths
        WHEN process_batch is called with duplicates
        THEN it should:
         - Process each path as a separate job (including duplicates)
         - Create distinct jobs even for same file
         - Handle duplicate processing appropriately
         - Maintain correct job count including duplicates
        """
        duplicate_files = sample_pdf_files + [sample_pdf_files[0]]  # Add duplicate
        
        batch_id = await processor.process_batch(pdf_paths=duplicate_files)
        
        batch_status = processor.active_batches[batch_id]
        assert batch_status.total_jobs == 4  # 3 original + 1 duplicate
        assert processor.job_queue.qsize() == 4

    @pytest.mark.asyncio
    async def test_process_batch_concurrent_batches(self, processor, sample_pdf_files):
        """
        GIVEN multiple concurrent batch processing requests
        WHEN process_batch is called multiple times concurrently
        THEN it should:
         - Handle concurrent batch creation properly
         - Create unique batch IDs for each batch
         - Maintain separate BatchStatus entries
         - Allow concurrent processing without conflicts
        """
        # Create additional PDF files for second batch
        with tempfile.TemporaryDirectory() as temp_dir:
            second_batch_files = []
            for i in range(2):
                pdf_path = Path(temp_dir) / f"second_batch_{i}.pdf"
                pdf_path.write_text(f"content {i}")
                second_batch_files.append(str(pdf_path))
            
            # Start both batches concurrently
            batch1_task = asyncio.create_task(processor.process_batch(pdf_paths=sample_pdf_files))
            batch2_task = asyncio.create_task(processor.process_batch(pdf_paths=second_batch_files))
            
            batch1_id, batch2_id = await asyncio.gather(batch1_task, batch2_task)
            
            # Verify both batches were created
            assert batch1_id != batch2_id
            assert batch1_id in processor.active_batches
            assert batch2_id in processor.active_batches
            assert processor.active_batches[batch1_id].total_jobs == 3
            assert processor.active_batches[batch2_id].total_jobs == 2



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
