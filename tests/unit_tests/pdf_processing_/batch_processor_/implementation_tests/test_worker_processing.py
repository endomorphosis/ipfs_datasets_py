# Test file for TestBatchProcessorWorkerProcessing class
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


class TestBatchProcessorWorkerProcessing:
    """Test class for worker processing and job handling methods in BatchProcessor."""

    @pytest.fixture
    def processor(self):
        """Create a BatchProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(max_workers=4, max_memory_mb=2048)
            return processor

    def test_worker_loop_basic_functionality(self, processor):
        """
        GIVEN a worker thread and jobs in the queue
        WHEN _worker_loop is executed
        THEN it should:
         - Continuously poll the job queue for new jobs
         - Process each job through _process_single_job
         - Update batch status after job completion
         - Mark queue tasks as done
         - Continue until stop_event is set
         - Handle queue timeout gracefully
        """
        # Create a mock job
        mock_job = Mock(spec=ProcessingJob)
        mock_job.job_id = "test_job_1"
        mock_job.metadata = {'batch_id': 'test_batch'}
        
        # Mock the async processing method
        processor._process_single_job = AsyncMock()
        processor._update_batch_status = Mock()
        
        # Add job to queue
        processor.job_queue.put(mock_job)
        processor.job_queue.put(None)  # Signal to stop
        
        # Run worker loop
        processor._worker_loop("test_worker")
        
        # Verify job was processed
        processor._process_single_job.assert_called_once_with(mock_job, "test_worker")
        processor._update_batch_status.assert_called_once()

    def test_worker_loop_stop_signal_handling(self, processor):
        """
        GIVEN a worker thread running _worker_loop
        WHEN stop_event is set
        THEN it should:
         - Exit the worker loop gracefully
         - Complete current job before stopping
         - Not process new jobs after stop signal
         - Clean up resources properly
         - Log worker shutdown
        """
        processor._process_single_job = AsyncMock()
        processor._update_batch_status = Mock()
        
        # Set stop event immediately
        processor.stop_event.set()
        
        # Worker loop should exit quickly
        start_time = time.time()
        processor._worker_loop("test_worker")
        end_time = time.time()
        
        # Should exit quickly (within 2 seconds due to queue timeout)
        assert end_time - start_time < 3
        
        # Should not have processed any jobs
        processor._process_single_job.assert_not_called()

    def test_worker_loop_exception_handling(self, processor):
        """
        GIVEN a worker processing jobs
        WHEN an exception occurs during job processing
        THEN it should:
         - Log the exception with job details
         - Continue processing other jobs
         - Not crash the worker thread
         - Update batch status appropriately for failed job
         - Maintain worker availability for future jobs
        """
        # Create mock jobs
        failing_job = Mock(spec=ProcessingJob)
        failing_job.job_id = "failing_job"
        failing_job.metadata = {'batch_id': 'test_batch'}
        
        good_job = Mock(spec=ProcessingJob)
        good_job.job_id = "good_job"
        good_job.metadata = {'batch_id': 'test_batch'}
        
        # Mock processing to fail on first job, succeed on second
        processor._process_single_job = AsyncMock()
        processor._process_single_job.side_effect = [
            Exception("Processing failed"),
            Mock()  # Success for second job
        ]
        processor._update_batch_status = Mock()
        
        # Add jobs to queue
        processor.job_queue.put(failing_job)
        processor.job_queue.put(good_job)
        processor.job_queue.put(None)  # Stop signal
        
        # Worker should handle exception and continue
        processor._worker_loop("test_worker")
        
        # Both jobs should have been attempted
        assert processor._process_single_job.call_count == 2

    def test_worker_loop_queue_timeout_behavior(self, processor):
        """
        GIVEN a worker waiting for jobs
        WHEN the job queue is empty for extended period
        THEN it should:
         - Use timeout on queue.get() to check stop_event periodically
         - Not block indefinitely waiting for jobs
         - Respond to stop_event within reasonable time
         - Continue checking for jobs until stopped
        """
        processor._process_single_job = AsyncMock()
        
        # Start worker loop in background
        import threading
        worker_thread = threading.Thread(
            target=processor._worker_loop,
            args=("timeout_test_worker",),
            daemon=True
        )
        worker_thread.start()
        
        # Let it run briefly
        time.sleep(0.5)
        
        # Set stop event
        processor.stop_event.set()
        
        # Worker should stop within reasonable time (queue timeout is 1 second)
        worker_thread.join(timeout=3)
        assert not worker_thread.is_alive()

    def test_worker_loop_job_processing_flow(self, processor):
        """
        GIVEN a complete job processing scenario
        WHEN worker processes multiple jobs of different types
        THEN it should:
         - Handle successful job completion properly
         - Handle failed job completion properly
         - Update batch status for each outcome
         - Maintain proper job queue management
         - Process jobs in FIFO order
        """
        # Create mock jobs with different outcomes
        successful_job = Mock(spec=ProcessingJob)
        successful_job.job_id = "success_job"
        successful_job.metadata = {'batch_id': 'test_batch'}
        
        failed_job = Mock(spec=ProcessingJob)
        failed_job.job_id = "failed_job"
        failed_job.metadata = {'batch_id': 'test_batch'}
        
        # Mock processing outcomes
        success_result = Mock()
        success_result.status = 'completed'
        
        failed_result = Mock()
        failed_result.status = 'failed'
        
        processor._process_single_job = AsyncMock()
        processor._process_single_job.side_effect = [success_result, failed_result]
        processor._update_batch_status = Mock()
        
        # Add jobs to queue
        processor.job_queue.put(successful_job)
        processor.job_queue.put(failed_job)
        processor.job_queue.put(None)  # Stop signal
        
        # Process jobs
        processor._worker_loop("test_worker")
        
        # Verify both jobs were processed
        assert processor._process_single_job.call_count == 2
        assert processor._update_batch_status.call_count == 2
        
        # Verify jobs were processed in order
        first_call = processor._process_single_job.call_args_list[0]
        second_call = processor._process_single_job.call_args_list[1]
        assert first_call[0][0] == successful_job
        assert second_call[0][0] == failed_job

    @pytest.mark.asyncio
    async def test_worker_memory_monitoring_integration(self, processor):
        """
        GIVEN workers processing jobs with memory monitoring enabled
        WHEN system memory usage approaches limits
        THEN it should:
         - Monitor memory usage during worker operations
         - Implement throttling when memory limits are approached
         - Log memory pressure warnings
         - Maintain system stability under memory pressure
        """
        processor.enable_monitoring = True
        processor._get_resource_usage = Mock(return_value={
            'memory_mb': processor.max_memory_mb - 100,  # Near limit
            'memory_percent': 85.0,
            'cpu_percent': 75.0,
            'active_workers': 4,
            'queue_size': 10
        })
        
        await processor._start_workers()
        
        # Verify workers were created despite memory pressure
        assert len(processor.workers) == processor.max_workers
        assert processor.is_processing is True

    def test_worker_loop_graceful_degradation(self, processor):
        """
        GIVEN system under stress or resource constraints
        WHEN worker encounters repeated processing failures
        THEN it should:
         - Continue attempting to process jobs
         - Not enter infinite failure loops
         - Implement backoff or throttling if needed
         - Maintain worker availability
         - Log appropriate error information
        """
        # Create multiple failing jobs
        failing_jobs = []
        for i in range(5):
            job = Mock(spec=ProcessingJob)
            job.job_id = f"failing_job_{i}"
            job.metadata = {'batch_id': 'test_batch'}
            failing_jobs.append(job)
        
        # Mock all jobs to fail
        processor._process_single_job = AsyncMock(side_effect=Exception("Persistent failure"))
        processor._update_batch_status = Mock()
        
        # Add failing jobs
        for job in failing_jobs:
            processor.job_queue.put(job)
        processor.job_queue.put(None)  # Stop signal
        
        # Worker should handle all failures without crashing
        processor._worker_loop("resilient_worker")
        
        # Verify all jobs were attempted
        assert processor._process_single_job.call_count == 5

    @pytest.mark.asyncio 
    async def test_worker_coordination_multiple_batches(self, processor):
        """
        GIVEN multiple concurrent batches being processed
        WHEN workers are processing jobs from different batches
        THEN it should:
         - Handle jobs from multiple batches correctly
         - Update appropriate batch status for each job
         - Maintain job isolation between batches
         - Process jobs fairly across batches
        """
        # Create jobs from different batches
        batch1_job = Mock(spec=ProcessingJob)
        batch1_job.job_id = "batch1_job"
        batch1_job.metadata = {'batch_id': 'batch_1'}
        
        batch2_job = Mock(spec=ProcessingJob)
        batch2_job.job_id = "batch2_job"
        batch2_job.metadata = {'batch_id': 'batch_2'}
        
        processor._process_single_job = AsyncMock(return_value=Mock(status='completed'))
        processor._update_batch_status = Mock()
        
        # Add jobs from different batches
        processor.job_queue.put(batch1_job)
        processor.job_queue.put(batch2_job)
        processor.job_queue.put(None)
        
        processor._worker_loop("multi_batch_worker")
        
        # Verify both jobs were processed
        assert processor._process_single_job.call_count == 2
        
        # Verify batch status was updated for both batches
        update_calls = processor._update_batch_status.call_args_list
        assert len(update_calls) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])