# Test file for TestProcessDirectoryBatch class
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/batch_processor.py
# Auto-generated on 2025-07-07 02:28:57"

import pytest
import os

from tests._test_utils import (
    raise_on_bad_callable_metadata,
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



class TestProcessDirectoryBatch:
    """Test class for process_directory_batch function."""

    @pytest.fixture
    def mock_batch_processor(self):
        """Create a mock BatchProcessor instance for testing."""
        processor = Mock(spec=BatchProcessor)
        processor.process_batch = AsyncMock(return_value="batch_abc123")
        return processor

    @pytest.fixture
    def temp_pdf_directory(self):
        """Create a temporary directory with sample PDF files for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create sample PDF files
            pdf_files = ["doc1.pdf", "doc2.pdf", "report_001.pdf", "report_002.pdf", "other.txt"]
            for filename in pdf_files:
                file_path = Path(temp_dir) / filename
                file_path.write_text(f"Mock PDF content for {filename}")
            yield temp_dir

    @pytest.mark.asyncio
    async def test_process_directory_batch_basic_functionality(self, mock_batch_processor, temp_pdf_directory):
        """
        GIVEN a directory containing multiple PDF files
        AND a properly configured BatchProcessor instance
        WHEN process_directory_batch is called with default parameters
        THEN it should:
         - Discover all PDF files in the directory using default "*.pdf" pattern
         - Call batch_processor.process_batch with the discovered file paths
         - Return the batch ID from the processor
         - Pass appropriate metadata including source directory information
        """
        batch_id = await process_directory_batch(
            directory_path=temp_pdf_directory,
            batch_processor=mock_batch_processor
        )
        
        # Verify batch_processor.process_batch was called
        mock_batch_processor.process_batch.assert_called_once()
        call_args = mock_batch_processor.process_batch.call_args
        
        # Extract the pdf_paths argument
        pdf_paths = call_args[0][0] if call_args[0] else call_args.kwargs.get('pdf_paths', [])
        
        # Should find 4 PDF files (doc1.pdf, doc2.pdf, report_001.pdf, report_002.pdf)
        assert len(pdf_paths) == 4
        assert all(str(path).endswith('.pdf') for path in pdf_paths)
        assert batch_id == "batch_abc123"

    @pytest.mark.asyncio
    async def test_process_directory_batch_with_custom_pattern(self, mock_batch_processor, temp_pdf_directory):
        """
        GIVEN a directory containing PDF files with different naming patterns
        AND a custom file pattern "report_*.pdf"
        WHEN process_directory_batch is called with the custom pattern
        THEN it should:
         - Only discover files matching the specific pattern
         - Exclude PDF files that don't match the pattern
         - Pass only matching files to the batch processor
        """
        batch_id = await process_directory_batch(
            directory_path=temp_pdf_directory,
            batch_processor=mock_batch_processor,
            file_pattern="report_*.pdf"
        )
        
        call_args = mock_batch_processor.process_batch.call_args
        pdf_paths = call_args[0][0] if call_args[0] else call_args.kwargs.get('pdf_paths', [])
        
        # Should find only 2 report PDF files
        assert len(pdf_paths) == 2
        assert all("report_" in str(path) for path in pdf_paths)
        assert batch_id == "batch_abc123"

    @pytest.mark.asyncio
    async def test_process_directory_batch_with_max_files_limit(self, mock_batch_processor, temp_pdf_directory):
        """
        GIVEN a directory containing 4 PDF files
        AND max_files parameter set to 2
        WHEN process_directory_batch is called with the file limit
        THEN it should:
         - Discover all matching PDF files
         - Limit the selection to the specified maximum number
         - Process exactly max_files number of documents
         - Select files in directory listing order
        """
        batch_id = await process_directory_batch(
            directory_path=temp_pdf_directory,
            batch_processor=mock_batch_processor,
            max_files=2
        )
        
        call_args = mock_batch_processor.process_batch.call_args
        pdf_paths = call_args[0][0] if call_args[0] else call_args.kwargs.get('pdf_paths', [])
        
        # Should process exactly 2 files despite 4 being available
        assert len(pdf_paths) == 2
        assert batch_id == "batch_abc123"

    @pytest.mark.asyncio
    async def test_process_directory_batch_nonexistent_directory(self, mock_batch_processor):
        """
        GIVEN a directory path that does not exist
        WHEN process_directory_batch is called with the invalid path
        THEN it should:
         - Raise ValueError with descriptive error message
         - Not call the batch processor
         - Provide clear indication of the missing directory
        """
        nonexistent_path = "/path/that/does/not/exist"
        
        with pytest.raises(ValueError) as exc_info:
            await process_directory_batch(
                directory_path=nonexistent_path,
                batch_processor=mock_batch_processor
            )
        
        assert "does not exist" in str(exc_info.value).lower()
        mock_batch_processor.process_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_directory_batch_empty_directory(self, mock_batch_processor):
        """
        GIVEN an empty directory with no PDF files
        WHEN process_directory_batch is called
        THEN it should:
         - Raise ValueError indicating no matching files found
         - Not call the batch processor
         - Provide clear error message about empty results
        """
        with tempfile.TemporaryDirectory() as empty_dir:
            with pytest.raises(ValueError) as exc_info:
                await process_directory_batch(
                    directory_path=empty_dir,
                    batch_processor=mock_batch_processor
                )
            
            assert "no matching files found" in str(exc_info.value).lower()
            mock_batch_processor.process_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_directory_batch_directory_with_no_matching_files(self, mock_batch_processor):
        """
        GIVEN a directory containing files but no PDF files
        WHEN process_directory_batch is called with default PDF pattern
        THEN it should:
         - Raise ValueError indicating no matching PDF files found
         - Not call the batch processor
         - Handle the case where directory exists but has no target files
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create non-PDF files
            (Path(temp_dir) / "document.txt").write_text("text content")
            (Path(temp_dir) / "image.jpg").write_text("image content")
            
            with pytest.raises(ValueError) as exc_info:
                await process_directory_batch(
                    directory_path=temp_dir,
                    batch_processor=mock_batch_processor
                )
            
            assert "no matching files found" in str(exc_info.value).lower()
            mock_batch_processor.process_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_directory_batch_invalid_batch_processor(self, temp_pdf_directory):
        """
        GIVEN a valid directory with PDF files
        AND an invalid batch_processor parameter (not a BatchProcessor instance)
        WHEN process_directory_batch is called
        THEN it should:
         - Raise TypeError indicating invalid processor type
         - Validate the processor parameter before processing
         - Provide clear error about expected processor type
        """
        invalid_processor = "not a batch processor"
        
        with pytest.raises(TypeError) as exc_info:
            await process_directory_batch(
                directory_path=temp_pdf_directory,
                batch_processor=invalid_processor
            )
        
        assert "BatchProcessor" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_process_directory_batch_negative_max_files(self, mock_batch_processor, temp_pdf_directory):
        """
        GIVEN a valid directory with PDF files
        AND max_files parameter set to a negative value
        WHEN process_directory_batch is called
        THEN it should:
         - Raise ValueError for negative max_files
         - Not process any files
         - Validate parameters before file discovery
        """
        with pytest.raises(ValueError) as exc_info:
            await process_directory_batch(
                directory_path=temp_pdf_directory,
                batch_processor=mock_batch_processor,
                max_files=-1
            )
        
        assert "positive" in str(exc_info.value).lower()
        mock_batch_processor.process_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_directory_batch_zero_max_files(self, mock_batch_processor, temp_pdf_directory):
        """
        GIVEN a valid directory with PDF files
        AND max_files parameter set to zero
        WHEN process_directory_batch is called
        THEN it should:
         - Raise ValueError for zero max_files
         - Not process any files
         - Require at least one file to be processed
        """
        with pytest.raises(ValueError) as exc_info:
            await process_directory_batch(
                directory_path=temp_pdf_directory,
                batch_processor=mock_batch_processor,
                max_files=0
            )
        
        assert "positive" in str(exc_info.value).lower()
        mock_batch_processor.process_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_directory_batch_permission_error(self, mock_batch_processor):
        """
        GIVEN a directory that exists but cannot be read due to permission restrictions
        WHEN process_directory_batch is called
        THEN it should:
         - Raise PermissionError with appropriate error message
         - Handle file system permission issues gracefully
         - Not call the batch processor
        """
        with patch('pathlib.Path.glob', side_effect=PermissionError("Permission denied")):
            with tempfile.TemporaryDirectory() as temp_dir:
                with pytest.raises(PermissionError):
                    await process_directory_batch(
                        directory_path=temp_dir,
                        batch_processor=mock_batch_processor
                    )
                
                mock_batch_processor.process_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_directory_batch_metadata_inclusion(self, mock_batch_processor, temp_pdf_directory):
        """
        GIVEN a directory with PDF files
        WHEN process_directory_batch is called successfully
        THEN it should:
         - Include batch metadata with source directory information
         - Pass metadata to the batch processor
         - Include file discovery details in metadata
         - Preserve directory path information for audit trails
        """
        await process_directory_batch(
            directory_path=temp_pdf_directory,
            batch_processor=mock_batch_processor,
            file_pattern="*.pdf",
            max_files=None
        )
        
        call_args = mock_batch_processor.process_batch.call_args
        batch_metadata = call_args.kwargs.get('batch_metadata', {})
        
        # Verify metadata includes source directory information
        assert 'source_directory' in batch_metadata
        assert batch_metadata['source_directory'] == temp_pdf_directory
        assert 'file_pattern' in batch_metadata
        assert batch_metadata['file_pattern'] == "*.pdf"

    @pytest.mark.asyncio
    async def test_process_directory_batch_path_object_support(self, mock_batch_processor, temp_pdf_directory):
        """
        GIVEN a directory path provided as a Path object instead of string
        WHEN process_directory_batch is called
        THEN it should:
         - Accept Path objects for cross-platform compatibility
         - Process the directory correctly regardless of path type
         - Convert paths appropriately for internal processing
        """
        path_object = Path(temp_pdf_directory)
        
        batch_id = await process_directory_batch(
            directory_path=path_object,
            batch_processor=mock_batch_processor
        )
        
        mock_batch_processor.process_batch.assert_called_once()
        assert batch_id == "batch_abc123"

    @pytest.mark.asyncio
    async def test_process_directory_batch_complex_glob_patterns(self, mock_batch_processor):
        """
        GIVEN a directory with various file types and naming patterns
        AND complex glob patterns with character classes and wildcards
        WHEN process_directory_batch is called with advanced patterns
        THEN it should:
         - Support advanced glob syntax correctly
         - Match files according to complex pattern specifications
         - Handle character classes, ranges, and multiple wildcards
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files with various patterns
            files = ["doc1.pdf", "doc2.pdf", "report2024.pdf", "report2025.pdf", "summary.pdf"]
            for filename in files:
                (Path(temp_dir) / filename).write_text("content")
            
            # Test pattern matching files with numbers
            batch_id = await process_directory_batch(
                directory_path=temp_dir,
                batch_processor=mock_batch_processor,
                file_pattern="*[0-9]*.pdf"
            )
            
            call_args = mock_batch_processor.process_batch.call_args
            pdf_paths = call_args[0][0] if call_args[0] else call_args.kwargs.get('pdf_paths', [])
            
            # Should match report2024.pdf, report2025.pdf, doc1.pdf, doc2.pdf
            assert len(pdf_paths) == 4
            assert batch_id == "batch_abc123"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
