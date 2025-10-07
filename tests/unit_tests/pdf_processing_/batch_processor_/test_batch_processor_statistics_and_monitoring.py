# Test file for TestBatchProcessorStatisticsAndMonitoring class
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


class TestBatchProcessorStatisticsAndMonitoring:
    """Test class for statistics and monitoring methods in BatchProcessor."""

    @pytest.fixture
    def processor(self, mock_storage, mock_pdf_processor, mock_llm_optimizer, mock_graphrag_integrator):
        """Create a BatchProcessor instance for testing with mocked dependencies."""
        processor = BatchProcessor(
            storage=mock_storage,
            pdf_processor=mock_pdf_processor,
            llm_optimizer=mock_llm_optimizer,
            graphrag_integrator=mock_graphrag_integrator,
            max_workers=4
        )
        processor._get_resource_usage = Mock(return_value={
            'memory_mb': 1024.0,
            'memory_percent': 25.0,
            'cpu_percent': 15.0,
            'active_workers': 4,
            'queue_size': 5
        })
        # Mock processing stats
        processor.processing_stats = {
            'total_processed': 0,
            'total_failed': 0,
            'total_processing_time': 0.0,
            'peak_memory_usage': 0.0,
            'average_throughput': 0.0,
            'batches_created': 0,
            'start_time': datetime.now().isoformat()
        }
        return processor

    @pytest.mark.asyncio
    async def test_get_processing_statistics_comprehensive(self, processor):
        """
        GIVEN a processor with various completed and failed jobs
        WHEN get_processing_statistics is called
        THEN it should:
         - Return comprehensive statistics across all operations
         - Calculate success rate correctly
         - Include timing and performance metrics
         - Provide current resource usage
         - Include batch and job counts
        """
        # Add completed and failed jobs to simulate processing history using batch_results
        completed_jobs = [
            BatchJobResult(job_id=f"completed_{i}", status='completed', processing_time=50.0 + i*10)
            for i in range(8)
        ]
        failed_jobs = [
            BatchJobResult(job_id=f"failed_{i}", status='failed', processing_time=25.0 + i*5)
            for i in range(2)
        ]
        
        # Store in batch_results structure instead of direct lists
        processor.batch_results['test_batch_1'] = {
            'completed': completed_jobs,
            'failed': failed_jobs
        }
        
        # Add some active batches
        processor.active_batches['batch_1'] = Mock()
        processor.active_batches['batch_2'] = Mock()
        
        stats = await processor.get_processing_statistics()
        
        assert stats['total_processed'] == 8
        assert stats['total_failed'] == 2
        assert stats['total_jobs'] == 10
        assert stats['success_rate'] == 0.8  # 8/10
        assert stats['total_processing_time'] == sum(job.processing_time for job in completed_jobs + failed_jobs)
        assert stats['average_job_time'] == sum(job.processing_time for job in completed_jobs) / 8
        assert stats['active_batches'] == 2
        assert stats['completed_jobs_count'] == 8
        assert stats['failed_jobs_count'] == 2
        assert 'resource_usage' in stats

    @pytest.mark.asyncio
    async def test_get_processing_statistics_zero_jobs(self, processor):
        """
        GIVEN a processor with no completed jobs
        WHEN get_processing_statistics is called
        THEN it should:
         - Handle zero division gracefully
         - Return appropriate default values
         - Calculate success rate as 0.0 for no jobs
         - Not raise mathematical errors
        """
        stats = await processor.get_processing_statistics()
        
        assert stats['total_processed'] == 0
        assert stats['total_failed'] == 0
        assert stats['total_jobs'] == 0
        assert stats['success_rate'] == 0.0
        assert stats['total_processing_time'] == 0.0
        assert stats['average_job_time'] == 0.0
        assert stats['active_batches'] == 0

    @pytest.mark.asyncio
    async def test_get_processing_statistics_only_failed_jobs(self, processor):
        """
        GIVEN a processor with only failed jobs
        WHEN get_processing_statistics is called
        THEN it should:
         - Calculate 0% success rate
         - Handle average_job_time for no successful jobs
         - Include failed job timing in total processing time
         - Return meaningful statistics
        """
        failed_jobs = [
            BatchJobResult(job_id=f"failed_{i}", status='failed', processing_time=30.0)
            for i in range(3)
        ]
        processor.batch_results['test_batch_failed'] = {
            'completed': [],
            'failed': failed_jobs
        }
        
        stats = await processor.get_processing_statistics()
        
        assert stats['total_processed'] == 0
        assert stats['total_failed'] == 3
        assert stats['total_jobs'] == 3
        assert stats['success_rate'] == 0.0
        assert stats['total_processing_time'] == 90.0  # 3 * 30.0
        assert stats['average_job_time'] == 0.0  # No successful jobs

    def test_get_resource_usage_comprehensive_metrics(self, processor):
        """
        GIVEN a processor with system monitoring enabled
        WHEN _get_resource_usage is called
        THEN it should:
         - Collect current memory usage in MB and percentage
         - Measure current CPU utilization
         - Count active worker threads
         - Report job queue size
         - Update peak memory tracking
         - Handle resource monitoring failures gracefully
        """
        # Remove the mock from the processor fixture for this test
        del processor._get_resource_usage
        
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.psutil.Process') as mock_process:
            # Mock system resource data
            mock_proc = Mock()
            mock_proc.memory_info.return_value.rss = 1073741824  # 1GB in bytes
            mock_proc.memory_percent.return_value = 50.0
            mock_proc.cpu_percent.return_value = 25.5
            mock_process.return_value = mock_proc
            
            # Set up active workers
            processor.workers = [Mock(), Mock(), Mock()]  # 3 active workers
            processor.job_queue.put("job1")
            processor.job_queue.put("job2")  # 2 jobs in queue
            
            usage = processor._get_resource_usage()
            
            assert usage['memory_mb'] == 1024.0  # 1GB converted to MB
            assert usage['memory_percent'] == 50.0
            assert usage['cpu_percent'] == 25.5
            assert usage['active_workers'] == 3
            assert usage['queue_size'] == 2
            assert 'peak_memory_mb' in usage

    def test_get_resource_usage_peak_memory_tracking(self, processor):
        """
        GIVEN multiple calls to _get_resource_usage with varying memory usage
        WHEN memory usage increases over time
        THEN it should:
         - Track and update peak memory usage
         - Maintain peak across multiple calls
         - Include peak memory in returned statistics
         - Update peak only when exceeded
        """
        # Remove the mock from the processor fixture for this test
        del processor._get_resource_usage
        
        processor.processing_stats['peak_memory_usage'] = 512.0  # Initial peak
        
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.psutil.Process') as mock_process:
            mock_proc = Mock()
            # First call - lower than peak
            mock_proc.memory_info.return_value.rss = 268435456  # 256MB
            mock_proc.memory_percent.return_value = 25.0
            mock_proc.cpu_percent.return_value = 15.0
            mock_process.return_value = mock_proc
            
            usage1 = processor._get_resource_usage()
            assert usage1['memory_mb'] == 256.0
            assert processor.processing_stats['peak_memory_usage'] == 512.0  # Unchanged
            
            # Second call - higher than peak
            mock_proc.memory_info.return_value.rss = 1073741824  # 1GB
            usage2 = processor._get_resource_usage()
            assert usage2['memory_mb'] == 1024.0
            assert processor.processing_stats['peak_memory_usage'] == 1024.0  # Updated

    def test_get_resource_usage_monitoring_failure(self, processor):
        """
        GIVEN system resource monitoring that fails
        WHEN _get_resource_usage encounters monitoring errors
        THEN it should:
         - Handle psutil import/access errors gracefully
         - Return default/fallback values
         - Log appropriate warnings
         - Not crash the processor
        """
        with patch('psutil.Process', side_effect=ImportError("psutil not available")):
            # Should handle gracefully and not raise
            usage = processor._get_resource_usage()
            
            # Should return some form of usage data or handle error appropriately
            assert isinstance(usage, dict)

    @pytest.mark.asyncio
    async def test_batch_lifecycle_integration(self, processor):
        """
        GIVEN a complete batch processing lifecycle
        WHEN batch is created, monitored, and completed
        THEN it should:
         - Maintain consistent batch status throughout lifecycle
         - Update statistics appropriately at each stage
         - Handle status transitions correctly
         - Provide accurate final metrics
        """
        from ipfs_datasets_py.pdf_processing.batch_processor import ProcessingJob, BatchJobResult
        
        # Create initial batch
        batch_id = "lifecycle_test_batch"
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
        
        # Simulate job completions
        jobs = [
            ProcessingJob(job_id=f"job_{i}", pdf_path=f"/doc_{i}.pdf",
                         metadata={'batch_id': batch_id}) for i in range(3)
        ]
        
        results = [
            BatchJobResult(job_id="job_0", status='completed', processing_time=60.0),
            BatchJobResult(job_id="job_1", status='failed', processing_time=30.0),
            BatchJobResult(job_id="job_2", status='completed', processing_time=90.0)
        ]
        
        # Process each job result using batch_results structure
        processor.batch_results[batch_id] = {'completed': [], 'failed': []}
        for job, result in zip(jobs, results):
            processor._update_batch_status(job, result)
            if result.status == 'completed':
                processor.batch_results[batch_id]['completed'].append(result)
            else:
                processor.batch_results[batch_id]['failed'].append(result)
        
        # Verify final batch state
        final_status = processor.active_batches[batch_id]
        assert final_status.completed_jobs == 2
        assert final_status.failed_jobs == 1
        assert final_status.pending_jobs == 0
        assert final_status.total_processing_time == 180.0
        assert final_status.average_job_time == 60.0  # (60 + 30 + 90) / 3
        assert final_status.end_time is not None
        
        # Verify processor statistics
        stats = await processor.get_processing_statistics()
        assert stats['total_processed'] >= 2
        assert stats['total_failed'] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])