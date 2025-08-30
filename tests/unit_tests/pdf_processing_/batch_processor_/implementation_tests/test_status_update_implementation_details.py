# Test file for BatchProcessor Status Update Implementation Details
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


class TestBatchProcessorStatusUpdateImplementationDetails:
    """Test class for batch status update implementation details."""

    @pytest.fixture
    def processor(self):
        """Create a BatchProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(max_workers=4)
            processor._get_resource_usage = Mock(return_value={
                'memory_mb': 1024.0,
                'memory_percent': 25.0,
                'cpu_percent': 15.0,
                'active_workers': 4,
                'queue_size': 10
            })
            return processor

    def test_update_batch_status_successful_job(self, processor):
        """
        GIVEN a batch with pending jobs and a successful job result
        WHEN _update_batch_status is called with completed job
        THEN it should:
         - Increment completed_jobs count
         - Decrement pending_jobs count
         - Update total_processing_time
         - Recalculate average_job_time
         - Keep end_time as None (batch not complete)
         - Maintain other counters unchanged
        """
        # Setup initial batch status
        batch_id = "batch_test_123"
        initial_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=5,
            completed_jobs=2,
            failed_jobs=0,
            pending_jobs=3,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=100.0,
            average_job_time=50.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = initial_status
        
        # Create successful job and result
        job = ProcessingJob(
            job_id="job_1",
            pdf_path="/test.pdf",
            metadata={'batch_id': batch_id}
        )
        result = BatchJobResult(
            job_id="job_1",
            status='completed',
            processing_time=45.0,
            entity_count=10,
            relationship_count=15,
            chunk_count=5
        )
        
        processor._update_batch_status(job, result)
        
        updated_status = processor.active_batches[batch_id]
        assert updated_status.completed_jobs == 3
        assert updated_status.failed_jobs == 0
        assert updated_status.pending_jobs == 2
        assert updated_status.total_processing_time == 145.0
        assert updated_status.average_job_time == 145.0 / 3  # Total time / completed jobs
        assert updated_status.end_time is None

    def test_update_batch_status_failed_job(self, processor):
        """
        GIVEN a batch with pending jobs and a failed job result
        WHEN _update_batch_status is called with failed job
        THEN it should:
         - Increment failed_jobs count
         - Decrement pending_jobs count
         - Update total_processing_time (including failed job time)
         - Not affect average_job_time calculation (failed jobs excluded)
         - Keep batch as incomplete
        """
        batch_id = "batch_test_456"
        initial_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=4,
            completed_jobs=2,
            failed_jobs=0,
            pending_jobs=2,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=80.0,
            average_job_time=40.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = initial_status
        
        job = ProcessingJob(
            job_id="failed_job",
            pdf_path="/test.pdf",
            metadata={'batch_id': batch_id}
        )
        result = BatchJobResult(
            job_id="failed_job",
            status='failed',
            processing_time=25.0,
            error_message="Processing failed",
            entity_count=0,
            relationship_count=0,
            chunk_count=0
        )
        
        processor._update_batch_status(job, result)
        
        updated_status = processor.active_batches[batch_id]
        assert updated_status.completed_jobs == 2
        assert updated_status.failed_jobs == 1
        assert updated_status.pending_jobs == 1
        assert updated_status.total_processing_time == 105.0  # 80 + 25
        assert updated_status.average_job_time == 35.0  # Total time / total finished jobs (105.0 / 3)

    def test_update_batch_status_batch_completion(self, processor):
        """
        GIVEN a batch with only one pending job remaining
        WHEN _update_batch_status is called with the final job result
        THEN it should:
         - Mark batch as complete by setting end_time
         - Calculate final throughput (jobs per second)
         - Update all job counters appropriately
         - Calculate final batch metrics
        """
        batch_id = "batch_final_test"
        initial_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=3,
            completed_jobs=2,
            failed_jobs=0,
            pending_jobs=1,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=90.0,
            average_job_time=45.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = initial_status
        
        job = ProcessingJob(
            job_id="final_job",
            pdf_path="/test.pdf",
            metadata={'batch_id': batch_id}
        )
        result = BatchJobResult(
            job_id="final_job",
            status='completed',
            processing_time=30.0,
            entity_count=5,
            relationship_count=8,
            chunk_count=3
        )
        
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.datetime') as mock_datetime:
            # Mock datetime.now() to return a controlled timestamp
            mock_now = Mock()
            mock_now.isoformat.return_value = "2024-01-01T10:05:00"
            mock_datetime.now.return_value = mock_now
            
            # Keep the original fromisoformat method for actual datetime parsing
            mock_datetime.fromisoformat = datetime.fromisoformat
            
            processor._update_batch_status(job, result)
        
        updated_status = processor.active_batches[batch_id]
        assert updated_status.completed_jobs == 3
        assert updated_status.failed_jobs == 0
        assert updated_status.pending_jobs == 0
        assert updated_status.end_time == "2024-01-01T10:05:00"
        assert updated_status.throughput > 0  # Should calculate throughput

    def test_update_batch_status_missing_batch_id(self, processor):
        """
        GIVEN a job with missing or invalid batch_id in metadata
        WHEN _update_batch_status is called
        THEN it should:
         - Handle the error gracefully without crashing
         - Log appropriate warning about missing batch
         - Not modify any batch status
         - Continue processing other jobs normally
        """
        job = ProcessingJob(
            job_id="orphan_job",
            pdf_path="/test.pdf",
            metadata={}  # Missing batch_id
        )
        result = BatchJobResult(
            job_id="orphan_job",
            status='completed',
            processing_time=30.0
        )
        
        # Should not raise exception
        processor._update_batch_status(job, result)
        
        # No batches should be modified
        assert len(processor.active_batches) == 0

    def test_update_batch_status_nonexistent_batch(self, processor):
        """
        GIVEN a job with batch_id that doesn't exist in active_batches
        WHEN _update_batch_status is called
        THEN it should:
         - Handle the missing batch gracefully
         - Log warning about orphaned job
         - Not create new batch status entry
         - Continue normal operation
        """
        job = ProcessingJob(
            job_id="orphan_job",
            pdf_path="/test.pdf",
            metadata={'batch_id': 'nonexistent_batch'}
        )
        result = BatchJobResult(
            job_id="orphan_job",
            status='completed',
            processing_time=30.0
        )
        
        processor._update_batch_status(job, result)
        
        assert 'nonexistent_batch' not in processor.active_batches


if __name__ == "__main__":
    pytest.main([__file__, "-v"])