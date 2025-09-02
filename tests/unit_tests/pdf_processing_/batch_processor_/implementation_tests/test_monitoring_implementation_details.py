# Test file for BatchProcessor Monitoring Implementation Details
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pytest
import os

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/batch_processor.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/batch_processor_stubs.md")

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


class TestBatchProcessorMonitoringImplementationDetails:
    """Test class for batch monitoring implementation details."""

    @pytest.fixture
    def processor(self, mock_storage, mock_pdf_processor, mock_llm_optimizer, mock_graphrag_integrator):
        """Create a BatchProcessor instance for testing."""
        processor = BatchProcessor(
            max_workers=4,
            storage=mock_storage,
            pdf_processor=mock_pdf_processor,
            llm_optimizer=mock_llm_optimizer,
            graphrag_integrator=mock_graphrag_integrator,
            enable_audit=False
        )
        processor._get_resource_usage = Mock(return_value={
            'memory_mb': 1024.0,
            'memory_percent': 25.0,
            'cpu_percent': 15.0,
            'active_workers': 4,
            'queue_size': 10
        })
        return processor

    @pytest.mark.asyncio
    async def test_monitor_batch_progress_callback_invocation(self, processor):
        """
        GIVEN an active batch and a progress callback function
        WHEN _monitor_batch_progress is called
        THEN it should:
         - Periodically invoke the callback with BatchStatus
         - Continue monitoring until batch completion
         - Handle both sync and async callbacks
         - Stop monitoring when batch completes
        """
        batch_id = "monitor_test_batch"
        callback_calls = []
        
        def progress_callback(status):
            callback_calls.append(status)
        
        # Create batch that will complete after a few updates
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=3,
            completed_jobs=0,
            failed_jobs=0,
            pending_jobs=3,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=0.0,
            average_job_time=0.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        
        # Simulate batch completion after short delay
        async def complete_batch():
            await asyncio.sleep(0.1)
            batch_status.completed_jobs = 3
            batch_status.pending_jobs = 0
            batch_status.end_time = "2024-01-01T10:05:00"
        
        # Start monitoring and batch completion concurrently
        monitor_task = asyncio.create_task(
            processor._monitor_batch_progress(batch_id, progress_callback)
        )
        complete_task = asyncio.create_task(complete_batch())
        
        await asyncio.wait([monitor_task, complete_task], return_when=asyncio.ALL_COMPLETED)
        
        # Verify callback was invoked
        assert len(callback_calls) > 0
        assert all(isinstance(call, BatchStatus) for call in callback_calls)

    @pytest.mark.asyncio
    async def test_monitor_batch_progress_async_callback(self, processor):
        """
        GIVEN an async callback function
        WHEN _monitor_batch_progress is called with async callback
        THEN it should:
         - Properly await async callback invocations
         - Handle async callback errors gracefully
         - Not block monitoring loop on callback execution
        """
        batch_id = "async_monitor_test"
        callback_calls = []
        
        async def async_progress_callback(status):
            await asyncio.sleep(0.01)  # Simulate async work
            callback_calls.append(status)
        
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=2,
            completed_jobs=0,
            failed_jobs=0,
            pending_jobs=2,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=0.0,
            average_job_time=0.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        
        # Complete batch quickly
        async def complete_batch():
            await asyncio.sleep(0.05)
            batch_status.completed_jobs = 2
            batch_status.pending_jobs = 0
            batch_status.end_time = "2024-01-01T10:05:00"
        
        monitor_task = asyncio.create_task(
            processor._monitor_batch_progress(batch_id, async_progress_callback)
        )
        complete_task = asyncio.create_task(complete_batch())
        
        await asyncio.wait([monitor_task, complete_task], return_when=asyncio.ALL_COMPLETED)
        
        assert len(callback_calls) > 0

    @pytest.mark.asyncio
    async def test_monitor_batch_progress_callback_error_handling(self, processor):
        """
        GIVEN a callback function that raises exceptions
        WHEN _monitor_batch_progress encounters callback errors
        THEN it should:
         - Log callback errors appropriately
         - Continue monitoring despite callback failures
         - Not terminate monitoring loop due to callback issues
         - Handle callback errors gracefully
        """
        batch_id = "error_callback_test"
        
        def failing_callback(status):
            raise Exception("Callback failed")
        
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=1,
            completed_jobs=0,
            failed_jobs=0,
            pending_jobs=1,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=0.0,
            average_job_time=0.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        
        # Complete batch to end monitoring
        async def complete_batch():
            await asyncio.sleep(0.05)
            batch_status.completed_jobs = 1
            batch_status.pending_jobs = 0
            batch_status.end_time = "2024-01-01T10:05:00"
        
        # Should not raise exception despite failing callback
        monitor_task = asyncio.create_task(
            processor._monitor_batch_progress(batch_id, failing_callback)
        )
        complete_task = asyncio.create_task(complete_batch())
        
        await asyncio.wait([monitor_task, complete_task], return_when=asyncio.ALL_COMPLETED)
        
        # Monitor should complete without raising exception

    @pytest.mark.asyncio
    async def test_monitor_batch_progress_nonexistent_batch(self, processor):
        """
        GIVEN a batch_id that doesn't exist
        WHEN _monitor_batch_progress is called
        THEN it should:
         - Exit immediately without calling the callback
         - Not raise exceptions or crash
         - Handle missing batch gracefully
        """
        callback_calls = []
        
        def dummy_callback(status):
            callback_calls.append(status)
        
        # Should not raise exception and should exit immediately
        await processor._monitor_batch_progress("nonexistent_batch", dummy_callback)
        
        # Callback should never be called for nonexistent batch
        assert len(callback_calls) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])