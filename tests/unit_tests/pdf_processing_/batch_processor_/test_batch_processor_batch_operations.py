# Test file for TestBatchProcessorBatchOperations class
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
import json
import csv
import tempfile
from pathlib import Path
from unittest.mock import patch
from ipfs_datasets_py.pdf_processing.batch_processor import (
    BatchProcessor, ProcessingJob, BatchJobResult, BatchStatus
)
from .conftest import (
    SAMPLE_BATCH_SIZE, SUCCESSFUL_JOBS_COUNT, FAILED_JOBS_COUNT, 
    PENDING_JOBS_COUNT, PROCESSING_TIME_FAST
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


class TestBatchProcessorBatchOperations:
    """Test class for batch operation methods (cancel and export) in BatchProcessor."""

    @pytest.fixture
    def cancel_batch_setup(self, processor):
        """Set up batch for cancellation testing."""
        batch_id = "batch_to_cancel"
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=SAMPLE_BATCH_SIZE,
            completed_jobs=1,
            failed_jobs=0,
            pending_jobs=PENDING_JOBS_COUNT,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            total_processing_time=50.0,
            average_job_time=50.0,
            throughput=0.0,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        
        # Add target jobs to queue
        target_jobs = [
            ProcessingJob(job_id=f"job_{i}", pdf_path=f"/doc_{i}.pdf", 
                         metadata={'batch_id': batch_id}) for i in range(PENDING_JOBS_COUNT)
        ]
        
        # Add other batch job
        other_job = ProcessingJob(job_id="other_job", pdf_path="/other.pdf",
                                metadata={'batch_id': "other_batch"})
        
        for job in target_jobs + [other_job]:
            processor.job_queue.put(job)
            
        return batch_id, batch_status

    @pytest.mark.asyncio
    async def test_cancel_batch_returns_true_on_success(self, cancel_batch_setup):
        """
        GIVEN an active batch with pending jobs in the queue
        WHEN cancel_batch is called
        THEN it should return True indicating successful cancellation
        """
        batch_id, batch_status = cancel_batch_setup
        processor = cancel_batch_setup[0]  # Get processor from setup
        result = await processor.cancel_batch(batch_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_batch_sets_end_time(self, cancel_batch_setup):
        """
        GIVEN an active batch with pending jobs in the queue
        WHEN cancel_batch is called
        THEN it should set batch end_time to current timestamp
        """
        batch_id, batch_status = cancel_batch_setup
        processor = cancel_batch_setup[0]  # Get processor from setup
        await processor.cancel_batch(batch_id)
        assert batch_status.end_time is not None

    @pytest.mark.asyncio
    async def test_cancel_batch_removes_target_jobs(self, cancel_batch_setup):
        """
        GIVEN an active batch with pending jobs in the queue
        WHEN cancel_batch is called
        THEN it should remove all pending jobs for the batch from job_queue
        """
        batch_id, batch_status = cancel_batch_setup
        processor = cancel_batch_setup[0]  # Get processor from setup
        await processor.cancel_batch(batch_id)
        
        remaining_jobs = []
        while not processor.job_queue.empty():
            remaining_jobs.append(processor.job_queue.get())
        
        assert len(remaining_jobs) == 1

    @pytest.mark.asyncio
    async def test_cancel_batch_preserves_other_jobs(self, cancel_batch_setup):
        """
        GIVEN an active batch with pending jobs in the queue
        WHEN cancel_batch is called
        THEN it should preserve jobs for other batches in queue
        """
        batch_id, batch_status = cancel_batch_setup
        processor = cancel_batch_setup[0]  # Get processor from setup
        await processor.cancel_batch(batch_id)
        
        remaining_jobs = []
        while not processor.job_queue.empty():
            remaining_jobs.append(processor.job_queue.get())
        
        assert remaining_jobs[0].metadata['batch_id'] == "other_batch"

    @pytest.mark.asyncio
    async def test_cancel_batch_nonexistent_returns_false(self, processor):
        """
        GIVEN a batch_id that doesn't exist in active_batches
        WHEN cancel_batch is called
        THEN it should return False indicating batch not found
        """
        result = await processor.cancel_batch("nonexistent_batch")
        assert result is False

    @pytest.fixture
    def completed_batch_setup(self, processor):
        """Set up completed batch for testing."""
        batch_id = "completed_batch"
        batch_status = BatchStatus(
            batch_id=batch_id,
            total_jobs=SUCCESSFUL_JOBS_COUNT,
            completed_jobs=FAILED_JOBS_COUNT,
            failed_jobs=1,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            end_time="2024-01-01T10:15:00",
            total_processing_time=300.0,
            average_job_time=PROCESSING_TIME_FAST * 10,
            throughput=0.2,
            resource_usage={}
        )
        processor.active_batches[batch_id] = batch_status
        return batch_id, batch_status

    @pytest.mark.asyncio
    async def test_cancel_completed_batch_returns_false(self, completed_batch_setup):
        """
        GIVEN a batch that is already completed
        WHEN cancel_batch is called
        THEN it should return False indicating batch already complete
        """
        batch_id, batch_status = completed_batch_setup
        processor = completed_batch_setup[0]  # Get processor from setup
        result = await processor.cancel_batch(batch_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_completed_batch_preserves_end_time(self, completed_batch_setup):
        """
        GIVEN a batch that is already completed
        WHEN cancel_batch is called
        THEN it should not modify the completed batch status
        """
        batch_id, batch_status = completed_batch_setup
        processor = completed_batch_setup[0]  # Get processor from setup
        original_end_time = batch_status.end_time
        await processor.cancel_batch(batch_id)
        assert batch_status.end_time == original_end_time

    @pytest.mark.asyncio
    async def test_export_batch_results_json_creates_file(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN it should create JSON file with complete batch data
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

    @pytest.mark.asyncio
    async def test_export_batch_results_json_includes_batch_metadata(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN it should include batch metadata in the export
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            assert data['batch_id'] == batch_id
            assert data['batch_status']['total_jobs'] == SAMPLE_BATCH_SIZE

    @pytest.mark.asyncio
    async def test_export_batch_results_json_includes_job_counts(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN it should include job counts in hierarchical structure
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            assert data['batch_status']['completed_jobs'] == SUCCESSFUL_JOBS_COUNT
            assert data['batch_status']['failed_jobs'] == FAILED_JOBS_COUNT

    @pytest.mark.asyncio
    async def test_export_batch_results_json_includes_completed_jobs(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN it should include completed job details
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            assert len(data['completed_jobs']) == SUCCESSFUL_JOBS_COUNT

    @pytest.mark.asyncio
    async def test_export_batch_results_json_includes_failed_jobs(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN it should include failed job details
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            assert len(data['failed_jobs']) == FAILED_JOBS_COUNT

    @pytest.mark.asyncio
    async def test_export_batch_results_json_completed_job_status(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN completed jobs should have correct status
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            completed_job = data['completed_jobs'][0]
            assert completed_job['status'] == 'completed'

    @pytest.mark.asyncio
    async def test_export_batch_results_json_failed_job_status(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN failed jobs should have correct status
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            failed_job = data['failed_jobs'][0]
            assert failed_job['status'] == 'failed'

    @pytest.mark.asyncio
    async def test_export_batch_results_json_failed_job_error_message(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with completed and failed results
        WHEN export_batch_results is called with JSON format
        THEN failed jobs should include error messages
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.json"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="json",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                data = json.load(f)
            
            failed_job = data['failed_jobs'][0]
            assert 'error_message' in failed_job

    @pytest.mark.asyncio
    async def test_export_batch_results_csv_returns_correct_path(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with job results
        WHEN export_batch_results is called with CSV format
        THEN it should return the correct output path
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

    @pytest.mark.asyncio
    async def test_export_batch_results_csv_creates_file(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with job results
        WHEN export_batch_results is called with CSV format
        THEN it should create CSV file with flattened job result data
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.csv"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="csv",
                output_path=str(output_path)
            )
            
            assert output_path.exists()

    @pytest.mark.asyncio
    async def test_export_batch_results_csv_row_count(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with job results
        WHEN export_batch_results is called with CSV format
        THEN it should include all job results in tabular format
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.csv"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="csv",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            assert len(rows) == SAMPLE_BATCH_SIZE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_header", [
        'job_id', 'status', 'processing_time', 'entity_count', 
        'relationship_count', 'chunk_count', 'error_message'
    ])
    async def test_export_batch_results_csv_has_required_headers(self, processor, sample_batch_with_results, expected_header):
        """
        GIVEN a batch with job results
        WHEN export_batch_results is called with CSV format
        THEN it should provide headers for all result fields
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.csv"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="csv",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            headers = rows[0].keys()
            assert expected_header in headers

    @pytest.mark.asyncio
    async def test_export_batch_results_csv_completed_job_count(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with job results
        WHEN export_batch_results is called with CSV format
        THEN it should include completed jobs
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.csv"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="csv",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            completed_rows = [r for r in rows if r['status'] == 'completed']
            assert len(completed_rows) == SUCCESSFUL_JOBS_COUNT

    @pytest.mark.asyncio
    async def test_export_batch_results_csv_failed_job_count(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with job results
        WHEN export_batch_results is called with CSV format
        THEN it should include failed jobs
        """
        batch_id, batch_status, completed_results, failed_results = sample_batch_with_results
        
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "batch_export.csv"
            
            await processor.export_batch_results(
                batch_id=batch_id,
                format="csv",
                output_path=str(output_path)
            )
            
            with open(output_path, 'r') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            failed_rows = [r for r in rows if r['status'] == 'failed']
            assert len(failed_rows) == FAILED_JOBS_COUNT

    @pytest.mark.asyncio
    async def test_export_batch_results_default_filename_has_timestamp(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with results and no output_path specified
        WHEN export_batch_results is called
        THEN it should generate timestamped filename automatically
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with patch('pathlib.Path.cwd') as mock_cwd:
            with tempfile.TemporaryDirectory() as temp_dir:
                mock_cwd.return_value = Path(temp_dir)
                
                export_path = await processor.export_batch_results(
                    batch_id=batch_id,
                    format="json"
                )
                
                assert batch_id in export_path

    @pytest.mark.asyncio
    async def test_export_batch_results_default_filename_has_extension(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with results and no output_path specified
        WHEN export_batch_results is called
        THEN it should use appropriate file extension for format
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

    @pytest.mark.asyncio
    async def test_export_batch_results_default_filename_file_exists(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with results and no output_path specified
        WHEN export_batch_results is called
        THEN it should create file in current directory
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with patch('pathlib.Path.cwd') as mock_cwd:
            with tempfile.TemporaryDirectory() as temp_dir:
                mock_cwd.return_value = Path(temp_dir)
                
                export_path = await processor.export_batch_results(
                    batch_id=batch_id,
                    format="json"
                )
                
                assert Path(export_path).exists()

    @pytest.mark.asyncio
    async def test_export_batch_results_invalid_format_raises_error(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with results
        WHEN export_batch_results is called with unsupported format
        THEN it should raise ValueError for unsupported format
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with pytest.raises(ValueError) as exc_info:
            await processor.export_batch_results(
                batch_id=batch_id,
                format="xml"
            )
        
        assert "format" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_export_batch_results_invalid_format_mentions_supported(self, processor, sample_batch_with_results):
        """
        GIVEN a batch with results
        WHEN export_batch_results is called with unsupported format
        THEN it should indicate supported formats in error message
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with pytest.raises(ValueError) as exc_info:
            await processor.export_batch_results(
                batch_id=batch_id,
                format="xml"
            )
        
        error_msg = str(exc_info.value).lower()
        assert "json" in error_msg or "csv" in error_msg or "supported" in error_msg

    @pytest.mark.asyncio
    async def test_export_batch_results_nonexistent_batch_raises_error(self, processor):
        """
        GIVEN a batch_id that doesn't exist
        WHEN export_batch_results is called
        THEN it should raise ValueError indicating batch not found
        """
        with pytest.raises(ValueError) as exc_info:
            await processor.export_batch_results(
                batch_id="nonexistent_batch",
                format="json"
            )
        
        assert "batch" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_export_batch_results_nonexistent_batch_mentions_not_found(self, processor):
        """
        GIVEN a batch_id that doesn't exist
        WHEN export_batch_results is called
        THEN it should provide clear error message
        """
        with pytest.raises(ValueError) as exc_info:
            await processor.export_batch_results(
                batch_id="nonexistent_batch",
                format="json"
            )
        
        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_export_batch_results_permission_error_raises(self, processor, sample_batch_with_results):
        """
        GIVEN invalid output path with no write permissions
        WHEN export_batch_results is called
        THEN it should raise PermissionError for inaccessible location
        """
        batch_id, _, _, _ = sample_batch_with_results
        
        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                await processor.export_batch_results(
                    batch_id=batch_id,
                    format="json",
                    output_path="/root/restricted.json"
                )