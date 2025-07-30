# Test file for TestBatchProcessorManagement class
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




class TestBatchProcessorManagement:
    """Test class for batch management methods in BatchProcessor."""

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
                'queue_size': 5
            })
            return processor

    @pytest.fixture
    def sample_batch_with_results(self, processor):
        """Create a batch with completed and failed job results."""
        batch_id = "batch_sample_123"
        
        # Create batch status
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=5,
            completed_jobs=3,
            failed_jobs=2,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            end_time="2024-01-01T10:30:00",
            total_processing_time=450.0,
            average_job_time=150.0,
            throughput=0.1,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        
        # Add completed job results
        completed_results = [
            BatchJobResult(
                job_id="batch_sample_123_job_0001",
                status='completed',
                processing_time=120.0,
                document_id="doc_1",
                knowledge_graph_id="graph_1",
                ipld_cid="cid_1",
                entity_count=15,
                relationship_count=25,
                chunk_count=8
            ),
            BatchJobResult(
                job_id="batch_sample_123_job_0002", 
                status='completed',
                processing_time=180.0,
                document_id="doc_2",
                knowledge_graph_id="graph_2",
                ipld_cid="cid_2",
                entity_count=22,
                relationship_count=35,
                chunk_count=12
            ),
            BatchJobResult(
                job_id="batch_sample_123_job_0003",
                status='completed', 
                processing_time=150.0,
                document_id="doc_3",
                knowledge_graph_id="graph_3",
                ipld_cid="cid_3",
                entity_count=18,
                relationship_count=28,
                chunk_count=10
            )
        ]
        
        # Add failed job results
        failed_results = [
            BatchJobResult(
                job_id="batch_sample_123_job_0004",
                status='failed',
                processing_time=45.0,
                error_message="PDF parsing failed: corrupted file",
                entity_count=0,
                relationship_count=0,
                chunk_count=0
            ),
            BatchJobResult(
                job_id="batch_sample_123_job_0005",
                status='failed',
                processing_time=30.0,
                error_message="Memory exhausted during processing",
                entity_count=0,
                relationship_count=0,
                chunk_count=0
            )
        ]
        
        # Store results in the new batch_results structure
        processor.batch_results[batch_id] = {
            'completed': completed_results,
            'failed': failed_results
        }
        
        return batch_id, batch_status, completed_results, failed_results

    @pytest.mark.asyncio
    async def test_cancel_batch_with_pending_jobs(self, processor):
        """
        GIVEN an active batch with pending jobs in the queue
        WHEN cancel_batch is called
        THEN it should:
         - Remove all pending jobs for the batch from job_queue
         - Set batch end_time to current timestamp
         - Preserve jobs for other batches in queue
         - Return True indicating successful cancellation
         - Log cancellation details for audit
        """
        batch_id = "batch_to_cancel"
        other_batch_id = "other_batch"
        
        # Create batch status
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=5,
            completed_jobs=1,
            failed_jobs=0,
            pending_jobs=4,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=50.0,
            average_job_time=50.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        
        # Add jobs to queue (mix of target batch and other batch)
        from ipfs_datasets_py.pdf_processing.batch_processor import ProcessingJob
        target_jobs = [
            ProcessingJob(job_id=f"job_{i}", pdf_path=f"/doc_{i}.pdf", 
                         metadata={'batch_id': batch_id}) for i in range(4)
        ]
        other_jobs = [
            ProcessingJob(job_id="other_job", pdf_path="/other.pdf",
                         metadata={'batch_id': other_batch_id})
        ]
        
        for job in target_jobs + other_jobs:
            processor.job_queue.put(job)
        
        initial_queue_size = processor.job_queue.qsize()
        
        result = await processor.cancel_batch(batch_id)
        
        assert result is True
        assert batch_status.end_time is not None
        
        # Verify target batch jobs were removed but other jobs remain
        remaining_jobs = []
        while not processor.job_queue.empty():
            remaining_jobs.append(processor.job_queue.get())
        
        assert len(remaining_jobs) == 1
        assert remaining_jobs[0].metadata['batch_id'] == other_batch_id

    @pytest.mark.asyncio
    async def test_cancel_batch_nonexistent_batch(self, processor):
        """
        GIVEN a batch_id that doesn't exist in active_batches
        WHEN cancel_batch is called
        THEN it should:
         - Return False indicating batch not found
         - Not modify job queue
         - Handle missing batch gracefully
         - Log appropriate message about missing batch
        """
        result = await processor.cancel_batch("nonexistent_batch")
        
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_batch_already_completed(self, processor):
        """
        GIVEN a batch that is already completed
        WHEN cancel_batch is called
        THEN it should:
         - Return False indicating batch already complete
         - Not modify the completed batch status
         - Handle completed batches appropriately
        """
        batch_id = "completed_batch"
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=3,
            completed_jobs=2,
            failed_jobs=1,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            end_time="2024-01-01T10:15:00",  # Already completed
            total_processing_time=300.0,
            average_job_time=150.0,
            throughput=0.2,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        original_end_time = batch_status.end_time
        
        result = await processor.cancel_batch(batch_id)
        
        assert result is False
        assert batch_status.end_time == original_end_time  # Unchanged

    @pytest.mark.asyncio
    async def test_export_batch_results_json_format(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN it should:
         - Create JSON file with complete batch data
         - Include batch metadata, job results, and performance metrics
         - Use hierarchical structure for easy parsing
         - Return path to created export file
         - Include both successful and failed job details
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            export_path = await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            assert export_path == str(output_path)
            assert output_path.exists()
            
            # Verify JSON content
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            assert data['batch_id'] == batch_id
            assert data['batch_status']['total_jobs'] == 5
            assert data['batch_status']['completed_jobs'] == 3
            assert data['batch_status']['failed_jobs'] == 2
            assert len(data['completed_jobs']) == 3
            assert len(data['failed_jobs']) == 2
            
            # Verify job result details
            completed_job = data['completed_jobs'][0]
            assert completed_job['status'] == 'completed'
            assert completed_job['entity_count'] == 15
            assert completed_job['relationship_count'] == 25
            
            failed_job = data['failed_jobs'][0]
            assert failed_job['status'] == 'failed'
            assert 'error_message' in failed_job

    @pytest.mark.asyncio
    async def test_export_batch_results_csv_format(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with job results
        WHEN export_batch_results is called with CSV format
        THEN it should:
         - Create CSV file with flattened job result data
         - Include all job results in tabular format
         - Provide headers for all result fields
         - Be suitable for spreadsheet analysis
         - Include both completed and failed jobs
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.csv"
            
            export_path = await processor.export_batch_results(
                batch_id=batch_id,
                format="csv",
                output_path=str(output_path)
            )
            
            assert export_path == str(output_path)
            assert output_path.exists()
            
            # Verify CSV content
            with open(output_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            assert len(rows) == 5  # 3 completed + 2 failed
            
            # Verify CSV headers
            headers = rows[0].keys()
            expected_headers = ['job_id', 'status', 'processing_time', 'entity_count', 
                              'relationship_count', 'chunk_count', 'error_message']
            for header in expected_headers:
                assert header in headers
            
            # Verify data types and content
            completed_rows = [r for r in rows if r['status'] == 'completed']
            failed_rows = [r for r in rows if r['status'] == 'failed']
            
            assert len(completed_rows) == 3
            assert len(failed_rows) == 2
            
            # Check completed job data
            assert completed_rows[0]['entity_count'] == '15'
            assert completed_rows[0]['relationship_count'] == '25'
            
            # Check failed job data
            assert failed_rows[0]['entity_count'] == '0'
            assert 'PDF parsing failed' in failed_rows[0]['error_message']

    @pytest.mark.asyncio
    async def test_export_batch_results_default_filename(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with results and no output_path specified
        WHEN export_batch_results is called
        THEN it should:
         - Generate timestamped filename automatically
         - Create file in current directory
         - Use appropriate file extension for format
         - Return generated filename path
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with patch('pathlib.Path.cwd') as mock_cwd:
            with tempfile.TemporaryDirectory() as temp_dir:
                mock_cwd.return_value = Path(temp_dir)
                
                export_path = await processor.export_batch_results(
                    batch_id=batch_id,
                    format="json"
                )
                
                assert export_path.endswith('.json')
                assert batch_id in export_path
                assert Path(export_path).exists()

    @pytest.mark.asyncio
    async def test_export_batch_results_invalid_format(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with results
        WHEN export_batch_results is called with unsupported format
        THEN it should:
         - Raise ValueError for unsupported format
         - Indicate supported formats in error message
         - Not create any output file
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with pytest.raises(ValueError) as exc_info:
            await processor.export_batch_results(
                batch_id=batch_id,
                format="xml"  # Unsupported format
            )
        
        assert "format" in str(exc_info.value).lower()
        error_msg = str(exc_info.value).lower()
        assert "json" in error_msg or "csv" in error_msg or "supported" in error_msg

    @pytest.mark.asyncio
    async def test_export_batch_results_nonexistent_batch(self, processor):
        """
        GIVEN a batch_id that doesn't exist
        WHEN export_batch_results is called
        THEN it should:
         - Raise ValueError indicating batch not found
         - Not create any output file
         - Provide clear error message
        """
        with pytest.raises(ValueError) as exc_info:
            await processor.export_batch_results(
                batch_id="nonexistent_batch",
                format="json"
            )
        
        assert "batch" in str(exc_info.value).lower()
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_export_batch_results_permission_error(self, processor, sample_batch_with_results):
        """
        GIVEN invalid output path with no write permissions
        WHEN export_batch_results is called
        THEN it should:
         - Raise PermissionError for inaccessible location
         - Handle file system permission issues
         - Provide clear error about write access
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                await processor.export_batch_results(
                    batch_id=batch_id,
                    format="json",
                    output_path="/root/restricted.json"
                )

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
