# Test file for TestBatchProcessorStatusManagement class
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




class TestBatchProcessorStatusManagement:
    """Test class for batch status management methods in BatchProcessor."""

    @pytest.fixture
    def sample_batch_status(self):
        """Create a sample BatchStatus for testing."""
        return BatchStatus(
            batch_id="batch_test_123",
            total_jobs=10,
            completed_jobs=3,
            failed_jobs=1,
            pending_jobs=6,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            end_time=None,
            total_processing_time=150.5,
            average_job_time=37.625,
            throughput=0.0,
            resource_usage={}
        )



    @pytest.fixture
    def processor_with_mocked_resources(self, processor):
        """Create a processor with mocked resource usage."""
        from unittest.mock import MagicMock
        processor._get_resource_usage = MagicMock(return_value={
            'memory_mb': 1024.0,
            'cpu_percent': 25.5,
            'active_workers': 4,
            'queue_size': 10,
            'peak_memory_mb': 1200.0
        })
        return processor

    @pytest.mark.asyncio
    async def test_get_batch_status_existing_batch(self, processor_with_mocked_resources, sample_batch_status):
        """
        GIVEN an active batch in the processor
        WHEN get_batch_status is called with valid batch_id
        THEN it should:
         - Return complete batch status information as dictionary
         - Include current resource usage data
         - Provide all BatchStatus fields
         - Return real-time resource metrics
        """
        processor = processor_with_mocked_resources
        batch_id = "batch_test_123"
        processor.active_batches[batch_id] = sample_batch_status
        
        status_dict = await processor.get_batch_status(batch_id)
        
        assert status_dict is not None
        assert isinstance(status_dict, dict)
        assert status_dict['batch_id'] == batch_id
        assert status_dict['total_jobs'] == 10
        assert status_dict['completed_jobs'] == 3
        assert status_dict['failed_jobs'] == 1
        assert status_dict['pending_jobs'] == 6
        assert status_dict['start_time'] == "2024-01-01T10:00:00"
        assert 'resource_usage' in status_dict
        assert status_dict['resource_usage']['memory_mb'] == 1024.0

    @pytest.mark.asyncio
    async def test_get_batch_status_nonexistent_batch(self, processor):
        """
        GIVEN no batch with the specified ID
        WHEN get_batch_status is called with invalid batch_id
        THEN it should:
         - Return None instead of raising exception
         - Handle missing batch gracefully
         - Not create new batch entry
        """
        status = await processor.get_batch_status("nonexistent_batch")
        
        assert status is None

    @pytest.mark.asyncio
    async def test_get_batch_status_resource_usage_integration(self, processor_with_mocked_resources, sample_batch_status):
        """
        GIVEN an active batch
        WHEN get_batch_status is called
        THEN it should:
         - Call _get_resource_usage to get current system state
         - Include fresh resource data in response
         - Handle resource monitoring failures gracefully
        """
        processor = processor_with_mocked_resources
        batch_id = "batch_resource_test"
        processor.active_batches[batch_id] = sample_batch_status
        
        await processor.get_batch_status(batch_id)
        
        processor._get_resource_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_active_batches_multiple_batches(self, processor):
        """
        GIVEN multiple active batches with different completion states
        WHEN list_active_batches is called
        THEN it should:
         - Return only incomplete batches (completed + failed < total)
         - Include fresh resource usage for each batch
         - Exclude completed batches from results
         - Return list of status dictionaries
        """
        # Create active (incomplete) batch
        active_batch = BatchStatus(
            batch_id="active_batch",
            total_jobs=10,
            completed_jobs=3,
            failed_jobs=1,
            pending_jobs=6,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=100.0,
            average_job_time=25.0,
            throughput=0.0,
            resource_usage={}
        )
        
        # Create completed batch
        completed_batch = BatchStatus(
            batch_id="completed_batch",
            total_jobs=5,
            completed_jobs=4,
            failed_jobs=1,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T09:00:00",
            end_time="2024-01-01T09:30:00",
            total_processing_time=200.0,
            average_job_time=50.0,
            throughput=0.1,
            resource_usage={}
        )
        
        processor.active_batches["active_batch"] = active_batch
        processor.active_batches["completed_batch"] = completed_batch
        
        active_list = await processor.list_active_batches()
        
        assert len(active_list) == 1
        assert active_list[0]['batch_id'] == "active_batch"
        assert active_list[0]['pending_jobs'] == 6

    @pytest.mark.asyncio
    async def test_list_active_batches_no_active_batches(self, processor):
        """
        GIVEN no active batches or only completed batches
        WHEN list_active_batches is called
        THEN it should:
         - Return empty list
         - Not raise exceptions
         - Handle empty state gracefully
        """
        active_list = await processor.list_active_batches()
        
        assert active_list == []
        assert isinstance(active_list, list)






if __name__ == "__main__":
    pytest.main([__file__, "-v"])
