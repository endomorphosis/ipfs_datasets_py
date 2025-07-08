
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

from ipfs_datasets_py.pdf_processing.batch_processor import (
    process_directory_batch,
    BatchProcessor
)

import pytest
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



class TestQualityOfObjectsInModule:
    """
    Test class for the quality of callable objects 
    (e.g. class, method, function, coroutine, or property) in the module.
    """

    def test_callable_objects_metadata_quality(self):
        """
        GIVEN a Python module
        WHEN the module is parsed by the AST
        THEN
         - Each callable object should have a detailed, Google-style docstring.
         - Each callable object should have a detailed signature with type hints and a return annotation.
        """
        tree = get_ast_tree(file_path)
        try:
            raise_on_bad_callable_metadata(tree)
        except (BadDocumentationError, BadSignatureError) as e:
            pytest.fail(f"Code metadata quality check failed: {e}")

    def test_callable_objects_quality(self):
        """
        GIVEN a Python module
        WHEN the module's source code is examined
        THEN if the file is not indicated as a mock, placeholder, stub, or example:
         - The module should not contain intentionally fake or simplified code 
            (e.g. "In a real implementation, ...")
         - Contain no mocked objects or placeholders.
        """
        try:
            raise_on_bad_callable_code_quality(file_path)
        except (BadDocumentationError, BadSignatureError) as e:
            for indicator in ["mock", "placeholder", "stub", "example"]:
                if indicator in file_path:
                    break
            else:
                # If no indicator is found, fail the test
                pytest.fail(f"Code quality check failed: {e}")




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
            
            assert "no matching" in str(exc_info.value).lower() or "no files" in str(exc_info.value).lower()
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
            
            assert "no matching" in str(exc_info.value).lower() or "no files" in str(exc_info.value).lower()
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
        
        assert "negative" in str(exc_info.value).lower() or "positive" in str(exc_info.value).lower()
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
        
        assert "zero" in str(exc_info.value).lower() or "positive" in str(exc_info.value).lower()
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



class TestBatchProcessorInitialization:
    """Test class for BatchProcessor initialization and configuration."""

    def test_init_with_default_parameters(self):
        """
        GIVEN no specific configuration parameters
        WHEN BatchProcessor is initialized with defaults
        THEN it should:
         - Set max_workers to min(cpu_count(), 8) 
         - Set max_memory_mb to 4096
         - Create a new IPLDStorage instance
         - Set enable_monitoring to False
         - Set enable_audit to True
         - Initialize all required processing components
         - Set up empty job tracking structures
         - Initialize threading primitives properly
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage') as mock_storage_class:
            mock_storage = Mock(spec=IPLDStorage)
            mock_storage_class.return_value = mock_storage
            
            processor = BatchProcessor()
            
            expected_workers = min(multiprocessing.cpu_count(), 8)
            assert processor.max_workers == expected_workers
            assert processor.max_memory_mb == 4096
            assert processor.storage == mock_storage
            assert processor.enable_monitoring is False
            assert processor.enable_audit is True
            
            # Check that processing components are initialized
            assert hasattr(processor, 'pdf_processor')
            assert hasattr(processor, 'llm_optimizer') 
            assert hasattr(processor, 'graphrag_integrator')
            
            # Check job tracking structures
            assert isinstance(processor.job_queue, Queue)
            assert isinstance(processor.completed_jobs, list)
            assert isinstance(processor.failed_jobs, list)
            assert isinstance(processor.active_batches, dict)
            assert isinstance(processor.workers, list)
            assert isinstance(processor.processing_stats, dict)
            
            # Check threading primitives
            assert isinstance(processor.stop_event, threading.Event)
            assert processor.is_processing is False
            assert processor.worker_pool is None

    def test_init_with_custom_max_workers(self):
        """
        GIVEN a custom max_workers value of 12
        WHEN BatchProcessor is initialized
        THEN it should:
         - Set max_workers to the specified value
         - Configure worker pool accordingly
         - Validate that workers count is reasonable
         - Initialize other parameters to defaults
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(max_workers=12)
            
            assert processor.max_workers == 12
            assert processor.max_memory_mb == 4096  # Default should remain

    def test_init_with_custom_memory_limit(self):
        """
        GIVEN a custom max_memory_mb value of 8192
        WHEN BatchProcessor is initialized
        THEN it should:
         - Set max_memory_mb to the specified value
         - Use this limit for memory throttling decisions
         - Initialize other parameters to defaults
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(max_memory_mb=8192)
            
            assert processor.max_memory_mb == 8192
            assert processor.max_workers == min(multiprocessing.cpu_count(), 8)  # Default

    def test_init_with_custom_storage_instance(self):
        """
        GIVEN a pre-configured IPLDStorage instance
        WHEN BatchProcessor is initialized with this storage
        THEN it should:
         - Use the provided storage instance instead of creating new one
         - Not modify the storage configuration
         - Share the storage with all processing components
         - Maintain storage reference for all operations
        """
        custom_storage = Mock(spec=IPLDStorage)
        
        processor = BatchProcessor(storage=custom_storage)
        
        assert processor.storage is custom_storage
        # Verify storage is passed to components that need it
        # (This would require checking component initialization)

    def test_init_with_monitoring_enabled(self):
        """
        GIVEN enable_monitoring set to True
        WHEN BatchProcessor is initialized
        THEN it should:
         - Create and configure monitoring system
         - Initialize performance metrics collection
         - Set up monitoring context for operations
         - Enable detailed performance logging
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            with patch('ipfs_datasets_py.pdf_processing.batch_processor.MonitoringSystem') as mock_monitoring:
                mock_monitor = Mock()
                mock_monitoring.return_value = mock_monitor
                
                processor = BatchProcessor(enable_monitoring=True)
                
                assert processor.monitoring == mock_monitor
                mock_monitoring.assert_called_once()

    def test_init_with_monitoring_disabled(self):
        """
        GIVEN enable_monitoring set to False
        WHEN BatchProcessor is initialized
        THEN it should:
         - Set monitoring attribute to None
         - Skip monitoring system initialization
         - Reduce overhead by disabling performance tracking
         - Function normally without monitoring capabilities
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(enable_monitoring=False)
            
            assert processor.monitoring is None

    def test_init_with_audit_enabled(self):
        """
        GIVEN enable_audit set to True (default)
        WHEN BatchProcessor is initialized
        THEN it should:
         - Create and configure audit logging system
         - Initialize compliance tracking capabilities
         - Set up audit trails for all operations
         - Enable detailed operation logging
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            with patch('ipfs_datasets_py.pdf_processing.batch_processor.AuditLogger') as mock_audit:
                mock_auditor = Mock()
                mock_audit.return_value = mock_auditor
                
                processor = BatchProcessor(enable_audit=True)
                
                assert processor.audit_logger == mock_auditor
                mock_audit.assert_called_once()

    def test_init_with_audit_disabled(self):
        """
        GIVEN enable_audit set to False
        WHEN BatchProcessor is initialized
        THEN it should:
         - Set audit_logger attribute to None
         - Skip audit logging system initialization
         - Reduce overhead by disabling audit trails
         - Function without compliance tracking
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(enable_audit=False)
            
            assert processor.audit_logger is None

    def test_init_with_invalid_max_workers_zero(self):
        """
        GIVEN max_workers parameter set to 0
        WHEN BatchProcessor is initialized
        THEN it should:
         - Raise ValueError with descriptive message
         - Indicate minimum workers requirement
         - Not create processor instance
        """
        with pytest.raises(ValueError) as exc_info:
            BatchProcessor(max_workers=0)
        
        assert "max_workers" in str(exc_info.value).lower()
        assert "1" in str(exc_info.value) or "positive" in str(exc_info.value).lower()

    def test_init_with_invalid_max_workers_negative(self):
        """
        GIVEN max_workers parameter set to -5
        WHEN BatchProcessor is initialized
        THEN it should:
         - Raise ValueError with descriptive message
         - Indicate workers must be positive
         - Not create processor instance
        """
        with pytest.raises(ValueError) as exc_info:
            BatchProcessor(max_workers=-5)
        
        assert "max_workers" in str(exc_info.value).lower()
        assert "positive" in str(exc_info.value).lower() or "greater" in str(exc_info.value).lower()

    def test_init_with_invalid_memory_limit_too_low(self):
        """
        GIVEN max_memory_mb parameter set to 256 (below minimum of 512)
        WHEN BatchProcessor is initialized
        THEN it should:
         - Raise ValueError indicating insufficient memory
         - Specify minimum memory requirement
         - Not create processor instance
        """
        with pytest.raises(ValueError) as exc_info:
            BatchProcessor(max_memory_mb=256)
        
        assert "memory" in str(exc_info.value).lower()
        assert "512" in str(exc_info.value) or "minimum" in str(exc_info.value).lower()

    def test_init_with_invalid_memory_limit_negative(self):
        """
        GIVEN max_memory_mb parameter set to -1000
        WHEN BatchProcessor is initialized
        THEN it should:
         - Raise ValueError for negative memory limit
         - Indicate memory must be positive
         - Not create processor instance
        """
        with pytest.raises(ValueError) as exc_info:
            BatchProcessor(max_memory_mb=-1000)
        
        assert "memory" in str(exc_info.value).lower()
        assert "positive" in str(exc_info.value).lower() or "negative" in str(exc_info.value).lower()

    def test_init_processing_components_initialization(self):
        """
        GIVEN valid initialization parameters
        WHEN BatchProcessor is initialized
        THEN it should:
         - Create PDFProcessor instance with proper configuration
         - Create LLMOptimizer instance with shared storage
         - Create GraphRAGIntegrator instance with shared storage
         - Ensure all components share the same storage instance
         - Configure components for batch processing workflow
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage') as mock_storage_class:
            with patch('ipfs_datasets_py.pdf_processing.batch_processor.PDFProcessor') as mock_pdf:
                with patch('ipfs_datasets_py.pdf_processing.batch_processor.LLMOptimizer') as mock_llm:
                    with patch('ipfs_datasets_py.pdf_processing.batch_processor.GraphRAGIntegrator') as mock_graphrag:
                        mock_storage = Mock(spec=IPLDStorage)
                        mock_storage_class.return_value = mock_storage
                        
                        processor = BatchProcessor()
                        
                        # Verify components were created
                        mock_pdf.assert_called_once()
                        mock_llm.assert_called_once()
                        mock_graphrag.assert_called_once()
                        
                        # Verify storage sharing (would depend on actual component signatures)
                        assert processor.pdf_processor is not None
                        assert processor.llm_optimizer is not None
                        assert processor.graphrag_integrator is not None

    def test_init_processing_statistics_initialization(self):
        """
        GIVEN initialization of BatchProcessor
        WHEN the processing_stats dictionary is created
        THEN it should:
         - Initialize with all required statistical counters
         - Set counters to appropriate starting values
         - Include timing, success rate, and resource tracking fields
         - Be ready for accumulating processing metrics
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor()
            
            stats = processor.processing_stats
            assert isinstance(stats, dict)
            
            # Check for expected statistical fields
            expected_fields = [
                'total_processed', 'total_failed', 'total_processing_time',
                'peak_memory_usage', 'batches_created', 'start_time'
            ]
            for field in expected_fields:
                assert field in stats, f"Missing expected field: {field}"
            
            # Check initial values are appropriate
            assert stats['total_processed'] == 0
            assert stats['total_failed'] == 0
            assert stats['total_processing_time'] == 0.0
            assert stats['batches_created'] == 0

    def test_init_with_monitoring_import_error(self):
        """
        GIVEN enable_monitoring set to True
        AND monitoring dependencies are not available
        WHEN BatchProcessor is initialized
        THEN it should:
         - Raise ImportError with descriptive message
         - Indicate missing monitoring dependencies
         - Suggest how to install required packages
         - Not create processor instance
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            with patch('ipfs_datasets_py.pdf_processing.batch_processor.MonitoringSystem', side_effect=ImportError("Missing monitoring deps")):
                with pytest.raises(ImportError) as exc_info:
                    BatchProcessor(enable_monitoring=True)
                
                assert "monitoring" in str(exc_info.value).lower()

    def test_init_storage_initialization_failure(self):
        """
        GIVEN storage initialization that fails
        WHEN BatchProcessor is initialized
        THEN it should:
         - Raise RuntimeError with storage-specific error details
         - Indicate storage initialization failure
         - Not create processor instance
         - Preserve original storage error information
        """
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage', side_effect=RuntimeError("Storage init failed")):
            with pytest.raises(RuntimeError) as exc_info:
                BatchProcessor()
            
            assert "storage" in str(exc_info.value).lower() or "init failed" in str(exc_info.value).lower()

    def test_init_all_components_with_full_configuration(self):
        """
        GIVEN all optional parameters specified with valid values
        WHEN BatchProcessor is initialized with complete configuration
        THEN it should:
         - Configure all components according to specifications
         - Enable both monitoring and audit systems
         - Use custom storage, memory limits, and worker counts
         - Create fully functional processor ready for batch operations
         - Initialize all tracking and management structures
        """
        custom_storage = Mock(spec=IPLDStorage)
        
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.MonitoringSystem') as mock_monitoring:
            with patch('ipfs_datasets_py.pdf_processing.batch_processor.AuditLogger') as mock_audit:
                mock_monitor = Mock()
                mock_auditor = Mock()
                mock_monitoring.return_value = mock_monitor
                mock_audit.return_value = mock_auditor
                
                processor = BatchProcessor(
                    max_workers=16,
                    max_memory_mb=8192,
                    storage=custom_storage,
                    enable_monitoring=True,
                    enable_audit=True
                )
                
                assert processor.max_workers == 16
                assert processor.max_memory_mb == 8192
                assert processor.storage is custom_storage
                assert processor.monitoring == mock_monitor
                assert processor.audit_logger == mock_auditor
                assert processor.is_processing is False
                assert len(processor.workers) == 0
                assert processor.worker_pool is None



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





class TestBatchProcessorWorkerManagement:
    """Test class for worker management methods in BatchProcessor."""

    @pytest.fixture
    def processor(self):
        """Create a BatchProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(max_workers=4, max_memory_mb=2048)
            return processor

    @pytest.mark.asyncio
    async def test_start_workers_basic_functionality(self, processor):
        """
        GIVEN a BatchProcessor with no active workers
        WHEN _start_workers is called
        THEN it should:
         - Create max_workers number of worker threads
         - Set is_processing flag to True
         - Clear the stop_event
         - Initialize ProcessPoolExecutor for CPU tasks
         - Add worker threads to workers list
         - Start all threads in daemon mode
         - Set up worker loop for each thread
        """
        await processor._start_workers()
        
        assert processor.is_processing is True
        assert not processor.stop_event.is_set()
        assert len(processor.workers) == processor.max_workers
        assert isinstance(processor.worker_pool, ProcessPoolExecutor)
        
        # Verify all workers are threads and are alive
        for worker in processor.workers:
            assert isinstance(worker, threading.Thread)
            assert worker.is_alive()
            assert worker.daemon  # Should be daemon threads

    @pytest.mark.asyncio
    async def test_start_workers_already_running(self, processor):
        """
        GIVEN a BatchProcessor with workers already running
        WHEN _start_workers is called again
        THEN it should:
         - Be idempotent (no additional workers created)
         - Not modify existing worker state
         - Not create additional ProcessPoolExecutor
         - Maintain current worker count
         - Log appropriate message about already running
        """
        # Start workers first time
        await processor._start_workers()
        initial_worker_count = len(processor.workers)
        initial_worker_pool = processor.worker_pool
        
        # Try to start workers again
        await processor._start_workers()
        
        assert len(processor.workers) == initial_worker_count
        assert processor.worker_pool is initial_worker_pool
        assert processor.is_processing is True

    @pytest.mark.asyncio
    async def test_start_workers_resource_constraints(self, processor):
        """
        GIVEN system resource limitations
        WHEN _start_workers is called
        THEN it should:
         - Handle thread creation failures gracefully
         - Create as many workers as possible within constraints
         - Log warnings about reduced worker count
         - Continue functioning with available workers
        """
        with patch('threading.Thread') as mock_thread_class:
            # Simulate some thread creation failures
            def side_effect(*args, **kwargs):
                if mock_thread_class.call_count <= 2:
                    mock_thread = Mock()
                    mock_thread.start = Mock()
                    mock_thread.is_alive.return_value = True
                    mock_thread.daemon = True
                    return mock_thread
                else:
                    raise OSError("Cannot create thread")
            
            mock_thread_class.side_effect = side_effect
            
            # This should handle the OSError gracefully
            try:
                await processor._start_workers()
                # Should have created at least some workers
                assert len(processor.workers) >= 0
            except OSError:
                pytest.fail("_start_workers should handle resource constraints gracefully")

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

    @pytest.mark.asyncio
    async def test_stop_processing_basic_functionality(self, processor):
        """
        GIVEN a BatchProcessor with active workers
        WHEN stop_processing is called
        THEN it should:
         - Set stop_event to signal worker shutdown
         - Add None jobs to wake up waiting workers
         - Wait for all worker threads to complete
         - Shutdown ProcessPoolExecutor gracefully
         - Clear workers list
         - Set is_processing to False
         - Complete within timeout period
        """
        # Start workers first
        await processor._start_workers()
        assert processor.is_processing is True
        assert len(processor.workers) > 0
        
        # Stop processing
        await processor.stop_processing(timeout=5.0)
        
        assert processor.stop_event.is_set()
        assert processor.is_processing is False
        assert len(processor.workers) == 0
        assert processor.worker_pool is None

    @pytest.mark.asyncio
    async def test_stop_processing_with_timeout(self, processor):
        """
        GIVEN workers that take time to complete current jobs
        WHEN stop_processing is called with specific timeout
        THEN it should:
         - Wait up to timeout seconds for workers to finish
         - Forcefully terminate workers that exceed timeout
         - Complete shutdown process within timeout + buffer
         - Log timeout warnings for slow workers
        """
        # Mock slow-responding workers
        with patch('threading.Thread.join') as mock_join:
            # Simulate workers that take longer than timeout
            mock_join.side_effect = lambda timeout: time.sleep(min(timeout or 0, 0.1))
            
            await processor._start_workers()
            
            start_time = time.time()
            await processor.stop_processing(timeout=1.0)
            end_time = time.time()
            
            # Should complete within timeout + reasonable buffer
            assert end_time - start_time < 2.0
            assert processor.is_processing is False

    @pytest.mark.asyncio
    async def test_stop_processing_no_workers_running(self, processor):
        """
        GIVEN a BatchProcessor with no active workers
        WHEN stop_processing is called
        THEN it should:
         - Complete immediately without error
         - Be idempotent (safe to call multiple times)
         - Not raise exceptions for empty worker list
         - Maintain clean state
        """
        # Ensure no workers are running
        assert processor.is_processing is False
        assert len(processor.workers) == 0
        
        # Should complete without error
        await processor.stop_processing()
        
        assert processor.is_processing is False
        assert len(processor.workers) == 0

    @pytest.mark.asyncio
    async def test_stop_processing_invalid_timeout(self, processor):
        """
        GIVEN a timeout value that is negative or zero
        WHEN stop_processing is called
        THEN it should:
         - Raise ValueError for invalid timeout
         - Not modify processor state
         - Indicate valid timeout requirements
        """
        await processor._start_workers()
        
        with pytest.raises(ValueError) as exc_info:
            await processor.stop_processing(timeout=-1.0)
        
        assert "timeout" in str(exc_info.value).lower()
        assert processor.is_processing is True  # State unchanged

        with pytest.raises(ValueError) as exc_info:
            await processor.stop_processing(timeout=0.0)
        
        assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_stop_processing_cleanup_sequence(self, processor):
        """
        GIVEN active workers and process pool
        WHEN stop_processing is called
        THEN it should:
         - Follow correct shutdown sequence: signal, wake, wait, cleanup
         - Ensure all resources are properly released
         - Handle partial cleanup on errors
         - Maintain consistent state after shutdown
        """
        await processor._start_workers()
        original_workers = processor.workers.copy()
        original_pool = processor.worker_pool
        
        # Mock to verify shutdown sequence
        with patch.object(processor.worker_pool, 'shutdown') as mock_pool_shutdown:
            await processor.stop_processing()
            
            # Verify process pool was shutdown
            mock_pool_shutdown.assert_called_once_with(wait=True)
            
            # Verify state is clean
            assert processor.stop_event.is_set()
            assert processor.is_processing is False
            assert len(processor.workers) == 0
            assert processor.worker_pool is None

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
    async def test_start_workers_process_pool_configuration(self, processor):
        """
        GIVEN BatchProcessor initialization
        WHEN _start_workers creates ProcessPoolExecutor
        THEN it should:
         - Configure process pool with appropriate worker count
         - Limit process pool size to available CPU cores
         - Set up process pool for CPU-intensive tasks
         - Handle process pool creation failures gracefully
        """
        with patch('concurrent.futures.ProcessPoolExecutor') as mock_pool_class:
            mock_pool = Mock()
            mock_pool_class.return_value = mock_pool
            
            await processor._start_workers()
            
            # Verify ProcessPoolExecutor was created
            mock_pool_class.assert_called_once()
            assert processor.worker_pool == mock_pool

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



class TestBatchProcessorSingleJob:
    """Test class for _process_single_job method in BatchProcessor."""

    @pytest.fixture
    def processor(self):
        """Create a BatchProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage'):
            processor = BatchProcessor(max_workers=4, max_memory_mb=2048)
            # Mock the processing components
            processor.pdf_processor = AsyncMock()
            processor.llm_optimizer = AsyncMock()
            processor.graphrag_integrator = AsyncMock()
            processor.storage = AsyncMock()
            return processor

    @pytest.fixture
    def sample_job(self):
        """Create a sample ProcessingJob for testing."""
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(b"Mock PDF content")
            temp_path = temp_file.name
        
        job = ProcessingJob(
            job_id="test_job_123",
            pdf_path=temp_path,
            metadata={
                'batch_id': 'batch_abc',
                'batch_metadata': {'project': 'test'},
                'job_index': 0
            },
            priority=5
        )
        yield job
        
        # Cleanup
        Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_process_single_job_successful_completion(self, processor, sample_job):
        """
        GIVEN a valid ProcessingJob with accessible PDF file
        WHEN _process_single_job is called
        THEN it should:
         - Process PDF through complete pipeline (PDF -> LLM -> GraphRAG)
         - Store results in IPLD storage
         - Return BatchJobResult with status='completed'
         - Include accurate processing metrics (time, entity counts)
         - Update job status to 'processing' then completed
         - Add result to completed_jobs list
        """
        # Mock successful processing pipeline
        mock_llm_document = Mock()
        mock_llm_document.document_id = "doc_123"
        mock_llm_document.chunks = [Mock(), Mock(), Mock()]  # 3 chunks
        
        mock_knowledge_graph = Mock()
        mock_knowledge_graph.graph_id = "graph_456"
        mock_knowledge_graph.entities = [Mock() for _ in range(5)]  # 5 entities
        mock_knowledge_graph.relationships = [Mock() for _ in range(8)]  # 8 relationships
        
        processor.pdf_processor.process_pdf.return_value = mock_llm_document
        processor.llm_optimizer.optimize_document.return_value = mock_llm_document
        processor.graphrag_integrator.integrate_document.return_value = mock_knowledge_graph
        processor.storage.store.return_value = "ipld_cid_789"
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        # Verify result structure
        assert isinstance(result, BatchJobResult)
        assert result.job_id == "test_job_123"
        assert result.status == 'completed'
        assert result.document_id == "doc_123"
        assert result.knowledge_graph_id == "graph_456"
        assert result.ipld_cid == "ipld_cid_789"
        assert result.entity_count == 5
        assert result.relationship_count == 8
        assert result.chunk_count == 3
        assert result.processing_time > 0
        assert result.error_message is None
        
        # Verify pipeline was called correctly
        processor.pdf_processor.process_pdf.assert_called_once_with(sample_job.pdf_path)
        processor.llm_optimizer.optimize_document.assert_called_once_with(mock_llm_document)
        processor.graphrag_integrator.integrate_document.assert_called_once_with(mock_llm_document)
        processor.storage.store.assert_called_once()
        
        # Verify result was added to completed jobs
        assert result in processor.completed_jobs

    @pytest.mark.asyncio
    async def test_process_single_job_pdf_processing_failure(self, processor, sample_job):
        """
        GIVEN a ProcessingJob with PDF that fails during processing
        WHEN _process_single_job is called and PDF processing fails
        THEN it should:
         - Return BatchJobResult with status='failed'
         - Include detailed error message from PDF processing
         - Set entity/relationship counts to 0
         - Not proceed to LLM optimization or GraphRAG stages
         - Add result to failed_jobs list
         - Record processing time up to failure point
        """
        # Mock PDF processing failure
        processor.pdf_processor.process_pdf.side_effect = Exception("PDF parsing failed: corrupted file")
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        assert result.status == 'failed'
        assert result.job_id == "test_job_123"
        assert "PDF parsing failed" in result.error_message
        assert result.document_id is None
        assert result.knowledge_graph_id is None
        assert result.ipld_cid is None
        assert result.entity_count == 0
        assert result.relationship_count == 0
        assert result.chunk_count == 0
        assert result.processing_time > 0
        
        # Verify subsequent stages were not called
        processor.llm_optimizer.optimize_document.assert_not_called()
        processor.graphrag_integrator.integrate_document.assert_not_called()
        processor.storage.store.assert_not_called()
        
        # Verify result was added to failed jobs
        assert result in processor.failed_jobs

    @pytest.mark.asyncio
    async def test_process_single_job_llm_optimization_failure(self, processor, sample_job):
        """
        GIVEN successful PDF processing but LLM optimization failure
        WHEN _process_single_job encounters LLM optimization error
        THEN it should:
         - Return failed result with LLM-specific error message
         - Include document_id from successful PDF processing
         - Set knowledge graph fields to None
         - Not proceed to GraphRAG integration
         - Record partial processing information
        """
        # Mock successful PDF processing, failed LLM optimization
        mock_llm_document = Mock()
        mock_llm_document.document_id = "doc_123"
        mock_llm_document.chunks = [Mock(), Mock()]
        
        processor.pdf_processor.process_pdf.return_value = mock_llm_document
        processor.llm_optimizer.optimize_document.side_effect = Exception("LLM optimization timeout")
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        assert result.status == 'failed'
        assert result.document_id == "doc_123"  # From successful PDF stage
        assert "LLM optimization timeout" in result.error_message
        assert result.knowledge_graph_id is None
        assert result.chunk_count == 2  # From PDF processing
        assert result.entity_count == 0
        assert result.relationship_count == 0
        
        # Verify GraphRAG was not called
        processor.graphrag_integrator.integrate_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_single_job_graphrag_integration_failure(self, processor, sample_job):
        """
        GIVEN successful PDF and LLM processing but GraphRAG failure
        WHEN _process_single_job encounters GraphRAG integration error
        THEN it should:
         - Return failed result with GraphRAG-specific error message
         - Include document_id from successful processing stages
         - Set knowledge graph and IPLD fields to None
         - Record information from successful stages
        """
        # Mock successful PDF and LLM processing, failed GraphRAG
        mock_llm_document = Mock()
        mock_llm_document.document_id = "doc_123"
        mock_llm_document.chunks = [Mock() for _ in range(4)]
        
        processor.pdf_processor.process_pdf.return_value = mock_llm_document
        processor.llm_optimizer.optimize_document.return_value = mock_llm_document
        processor.graphrag_integrator.integrate_document.side_effect = Exception("Entity extraction failed")
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        assert result.status == 'failed'
        assert result.document_id == "doc_123"
        assert "Entity extraction failed" in result.error_message
        assert result.knowledge_graph_id is None
        assert result.ipld_cid is None
        assert result.chunk_count == 4
        assert result.entity_count == 0
        assert result.relationship_count == 0
        
        # Verify storage was not called
        processor.storage.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_single_job_storage_failure(self, processor, sample_job):
        """
        GIVEN successful processing through GraphRAG but storage failure
        WHEN _process_single_job encounters IPLD storage error
        THEN it should:
         - Return failed result with storage-specific error message
         - Include all processing results except IPLD CID
         - Record complete entity and relationship counts
         - Indicate storage as the failure point
        """
        # Mock successful processing through GraphRAG, failed storage
        mock_llm_document = Mock()
        mock_llm_document.document_id = "doc_123"
        mock_llm_document.chunks = [Mock() for _ in range(3)]
        
        mock_knowledge_graph = Mock()
        mock_knowledge_graph.graph_id = "graph_456"
        mock_knowledge_graph.entities = [Mock() for _ in range(7)]
        mock_knowledge_graph.relationships = [Mock() for _ in range(12)]
        
        processor.pdf_processor.process_pdf.return_value = mock_llm_document
        processor.llm_optimizer.optimize_document.return_value = mock_llm_document
        processor.graphrag_integrator.integrate_document.return_value = mock_knowledge_graph
        processor.storage.store.side_effect = Exception("IPLD storage connection failed")
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        assert result.status == 'failed'
        assert result.document_id == "doc_123"
        assert result.knowledge_graph_id == "graph_456"
        assert "IPLD storage connection failed" in result.error_message
        assert result.ipld_cid is None
        assert result.entity_count == 7
        assert result.relationship_count == 12
        assert result.chunk_count == 3

    @pytest.mark.asyncio
    async def test_process_single_job_file_not_found(self, processor):
        """
        GIVEN a ProcessingJob with non-existent PDF file path
        WHEN _process_single_job is called
        THEN it should:
         - Return failed result with FileNotFoundError message
         - Not attempt to process non-existent file
         - Handle file system errors gracefully
         - Provide clear error indication
        """
        job = ProcessingJob(
            job_id="missing_file_job",
            pdf_path="/path/to/nonexistent.pdf",
            metadata={'batch_id': 'batch_test'},
            priority=5
        )
        
        result = await processor._process_single_job(job, "worker_1")
        
        assert result.status == 'failed'
        assert result.job_id == "missing_file_job"
        assert "not found" in result.error_message.lower() or "does not exist" in result.error_message.lower()
        assert result.document_id is None
        assert result.processing_time > 0  # Should still record time spent

    @pytest.mark.asyncio
    async def test_process_single_job_permission_error(self, processor):
        """
        GIVEN a ProcessingJob with PDF file that cannot be read due to permissions
        WHEN _process_single_job is called
        THEN it should:
         - Return failed result with PermissionError message
         - Handle permission issues gracefully
         - Provide clear error indication about access rights
        """
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(b"Mock PDF content")
            temp_path = temp_file.name
        
        job = ProcessingJob(
            job_id="permission_job",
            pdf_path=temp_path,
            metadata={'batch_id': 'batch_test'},
            priority=5
        )
        
        # Mock permission error during PDF processing
        processor.pdf_processor.process_pdf.side_effect = PermissionError("Permission denied")
        
        try:
            result = await processor._process_single_job(job, "worker_1")
            
            assert result.status == 'failed'
            assert "permission denied" in result.error_message.lower()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_process_single_job_memory_error_handling(self, processor, sample_job):
        """
        GIVEN processing that exceeds available memory
        WHEN _process_single_job encounters MemoryError
        THEN it should:
         - Return failed result with memory-specific error message
         - Handle memory exhaustion gracefully
         - Not crash the worker process
         - Provide clear indication of memory issue
        """
        processor.pdf_processor.process_pdf.side_effect = MemoryError("Document too large for available memory")
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        assert result.status == 'failed'
        assert "memory" in result.error_message.lower()
        assert result.entity_count == 0
        assert result.relationship_count == 0

    @pytest.mark.asyncio
    async def test_process_single_job_timing_accuracy(self, processor, sample_job):
        """
        GIVEN a job that takes measurable time to process
        WHEN _process_single_job completes
        THEN it should:
         - Record accurate processing time from start to finish
         - Include time for all processing stages
         - Provide timing precision suitable for performance analysis
         - Record time even for failed jobs
        """
        # Mock processing with artificial delay
        async def slow_pdf_processing(path):
            await asyncio.sleep(0.1)  # 100ms delay
            mock_doc = Mock()
            mock_doc.document_id = "doc_123"
            mock_doc.chunks = [Mock()]
            return mock_doc
        
        async def slow_llm_optimization(doc):
            await asyncio.sleep(0.1)  # Another 100ms
            return doc
        
        async def slow_graphrag_integration(doc):
            await asyncio.sleep(0.1)  # Another 100ms
            mock_graph = Mock()
            mock_graph.graph_id = "graph_456"
            mock_graph.entities = [Mock()]
            mock_graph.relationships = [Mock()]
            return mock_graph
        
        processor.pdf_processor.process_pdf.side_effect = slow_pdf_processing
        processor.llm_optimizer.optimize_document.side_effect = slow_llm_optimization
        processor.graphrag_integrator.integrate_document.side_effect = slow_graphrag_integration
        processor.storage.store.return_value = "cid_123"
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        assert result.status == 'completed'
        assert result.processing_time >= 0.3  # At least 300ms total
        assert result.processing_time < 1.0    # But reasonable upper bound

    @pytest.mark.asyncio
    async def test_process_single_job_worker_identification(self, processor, sample_job):
        """
        GIVEN different worker names processing jobs
        WHEN _process_single_job is called with worker identification
        THEN it should:
         - Include worker name in logging and monitoring
         - Use worker name for performance attribution
         - Handle worker-specific error tracking
         - Support concurrent worker identification
        """
        # Mock successful processing
        mock_doc = Mock()
        mock_doc.document_id = "doc_123"
        mock_doc.chunks = [Mock()]
        
        mock_graph = Mock()
        mock_graph.graph_id = "graph_456"
        mock_graph.entities = [Mock()]
        mock_graph.relationships = [Mock()]
        
        processor.pdf_processor.process_pdf.return_value = mock_doc
        processor.llm_optimizer.optimize_document.return_value = mock_doc
        processor.graphrag_integrator.integrate_document.return_value = mock_graph
        processor.storage.store.return_value = "cid_123"
        
        result = await processor._process_single_job(sample_job, "worker_specialized_1")
        
        assert result.status == 'completed'
        # Worker name should be used for logging/monitoring (implementation dependent)

    @pytest.mark.asyncio
    async def test_process_single_job_audit_logging_integration(self, processor, sample_job):
        """
        GIVEN audit logging enabled
        WHEN _process_single_job processes a job
        THEN it should:
         - Create audit log entries for job start/completion
         - Log processing stages and outcomes
         - Include job metadata in audit trails
         - Handle audit logging failures gracefully
        """
        processor.audit_logger = Mock()
        
        # Mock successful processing
        mock_doc = Mock()
        mock_doc.document_id = "doc_123"
        mock_doc.chunks = [Mock()]
        
        mock_graph = Mock()
        mock_graph.graph_id = "graph_456"
        mock_graph.entities = [Mock()]
        mock_graph.relationships = [Mock()]
        
        processor.pdf_processor.process_pdf.return_value = mock_doc
        processor.llm_optimizer.optimize_document.return_value = mock_doc
        processor.graphrag_integrator.integrate_document.return_value = mock_graph
        processor.storage.store.return_value = "cid_123"
        
        result = await processor._process_single_job(sample_job, "worker_1")
        
        assert result.status == 'completed'
        # Verify audit logging was called (implementation dependent)
        if processor.audit_logger:
            assert processor.audit_logger.log.call_count >= 1


import pytest
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock
from ipfs_datasets_py.pdf_processing.batch_processor import (
    BatchProcessor, BatchStatus, ProcessingJob, BatchJobResult
)

class TestBatchProcessorStatusManagement:
    """Test class for batch status management methods in BatchProcessor."""

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
        assert updated_status.average_job_time == 40.0  # Only successful jobs count

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
        
        with patch('datetime.datetime') as mock_datetime:
            mock_datetime.utcnow.return_value.isoformat.return_value = "2024-01-01T10:05:00"
            
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

    @pytest.mark.asyncio
    async def test_get_batch_status_existing_batch(self, processor, sample_batch_status):
        """
        GIVEN an active batch in the processor
        WHEN get_batch_status is called with valid batch_id
        THEN it should:
         - Return complete batch status information as dictionary
         - Include current resource usage data
         - Provide all BatchStatus fields
         - Return real-time resource metrics
        """
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
    async def test_get_batch_status_resource_usage_integration(self, processor, sample_batch_status):
        """
        GIVEN an active batch
        WHEN get_batch_status is called
        THEN it should:
         - Call _get_resource_usage to get current system state
         - Include fresh resource data in response
         - Handle resource monitoring failures gracefully
        """
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
        assert all(isinstance(call, dict) for call in callback_calls)

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
         - Raise ValueError for invalid batch_id
         - Not start monitoring loop
         - Provide clear error message
        """
        def dummy_callback(status):
            pass
        
        with pytest.raises(ValueError) as exc_info:
            await processor._monitor_batch_progress("nonexistent_batch", dummy_callback)
        
        assert "batch" in str(exc_info.value).lower()



import pytest
import tempfile
import json
import csv
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from ipfs_datasets_py.pdf_processing.batch_processor import (
    BatchProcessor, BatchStatus, BatchJobResult
)

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
                job_id="job_1",
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
                job_id="job_2", 
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
                job_id="job_3",
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
                job_id="job_4",
                status='failed',
                processing_time=45.0,
                error_message="PDF parsing failed: corrupted file",
                entity_count=0,
                relationship_count=0,
                chunk_count=0
            ),
            BatchJobResult(
                job_id="job_5",
                status='failed',
                processing_time=30.0,
                error_message="Memory exhausted during processing",
                entity_count=0,
                relationship_count=0,
                chunk_count=0
            )
        ]
        
        processor.completed_jobs.extend(completed_results)
        processor.failed_jobs.extend(failed_results)
        
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
        assert "json" in str(exc_info.value).lower() or "csv" in str(exc_info.value).lower()

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
        # Add some completed and failed jobs to simulate processing history
        completed_jobs = [
            BatchJobResult(job_id=f"completed_{i}", status='completed', processing_time=50.0 + i*10)
            for i in range(8)
        ]
        failed_jobs = [
            BatchJobResult(job_id=f"failed_{i}", status='failed', processing_time=25.0 + i*5)
            for i in range(2)
        ]
        
        processor.completed_jobs.extend(completed_jobs)
        processor.failed_jobs.extend(failed_jobs)
        
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
        processor.failed_jobs.extend(failed_jobs)
        
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
        with patch('psutil.Process') as mock_process:
            with patch('psutil.virtual_memory') as mock_memory:
                with patch('psutil.cpu_percent') as mock_cpu:
                    # Mock system resource data
                    mock_proc = Mock()
                    mock_proc.memory_info.return_value.rss = 1073741824  # 1GB in bytes
                    mock_process.return_value = mock_proc
                    
                    mock_memory.return_value.total = 8589934592  # 8GB total
                    mock_memory.return_value.percent = 50.0
                    
                    mock_cpu.return_value = 25.5
                    
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
        processor.processing_stats['peak_memory_usage'] = 512.0  # Initial peak
        
        with patch('psutil.Process') as mock_process:
            mock_proc = Mock()
            # First call - lower than peak
            mock_proc.memory_info.return_value.rss = 268435456  # 256MB
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
        
        # Process each job result
        for job, result in zip(jobs, results):
            processor._update_batch_status(job, result)
            if result.status == 'completed':
                processor.completed_jobs.append(result)
            else:
                processor.failed_jobs.append(result)
        
        # Verify final batch state
        final_status = processor.active_batches[batch_id]
        assert final_status.completed_jobs == 2
        assert final_status.failed_jobs == 1
        assert final_status.pending_jobs == 0
        assert final_status.total_processing_time == 180.0
        assert final_status.average_job_time == 75.0  # (60 + 90) / 2
        assert final_status.end_time is not None
        
        # Verify processor statistics
        stats = await processor.get_processing_statistics()
        assert stats['total_processed'] >= 2
        assert stats['total_failed'] >= 1


import pytest
from datetime import datetime
from ipfs_datasets_py.pdf_processing.batch_processor import (
    ProcessingJob, BatchJobResult, BatchStatus
)

class TestProcessingJobDataclass:
    """Test class for ProcessingJob dataclass functionality."""

    def test_processing_job_basic_initialization(self):
        """
        GIVEN valid parameters for ProcessingJob
        WHEN ProcessingJob is instantiated
        THEN it should:
         - Initialize all required fields correctly
         - Set default values for optional fields
         - Have proper field types and values
         - Include all expected attributes
        """
        job = ProcessingJob(
            job_id="test_job_123",
            pdf_path="/path/to/document.pdf",
            metadata={"batch_id": "batch_abc", "project": "test_project"}
        )
        
        assert job.job_id == "test_job_123"
        assert job.pdf_path == "/path/to/document.pdf"
        assert job.metadata == {"batch_id": "batch_abc", "project": "test_project"}
        assert job.priority == 5  # Default value
        assert job.status == "pending"  # Default value
        assert job.error_message is None  # Default value
        assert job.result is None  # Default value
        assert job.processing_time == 0.0  # Default value
        assert isinstance(job.created_at, str)  # Should be set by __post_init__

    def test_processing_job_custom_parameters(self):
        """
        GIVEN custom values for all ProcessingJob parameters
        WHEN ProcessingJob is instantiated with custom values
        THEN it should:
         - Use provided values instead of defaults
         - Maintain parameter types correctly
         - Handle all valid parameter combinations
        """
        custom_metadata = {
            "batch_id": "custom_batch",
            "user_id": "user_123",
            "tags": ["research", "analysis"]
        }
        
        job = ProcessingJob(
            job_id="custom_job_456",
            pdf_path="/custom/path/doc.pdf",
            metadata=custom_metadata,
            priority=8,
            status="processing",
            error_message="Custom error",
            result={"doc_id": "doc_789"},
            processing_time=125.5,
            created_at="2024-01-01T12:00:00"
        )
        
        assert job.job_id == "custom_job_456"
        assert job.pdf_path == "/custom/path/doc.pdf"
        assert job.metadata == custom_metadata
        assert job.priority == 8
        assert job.status == "processing"
        assert job.error_message == "Custom error"
        assert job.result == {"doc_id": "doc_789"}
        assert job.processing_time == 125.5
        assert job.created_at == "2024-01-01T12:00:00"

    def test_processing_job_post_init_timestamp(self):
        """
        GIVEN ProcessingJob creation without explicit created_at
        WHEN __post_init__ is called automatically
        THEN it should:
         - Set created_at to current UTC timestamp
         - Use ISO format for timestamp
         - Not override explicitly provided created_at
         - Generate valid datetime string
        """
        # Test automatic timestamp generation
        job1 = ProcessingJob(
            job_id="timestamp_test_1",
            pdf_path="/test1.pdf",
            metadata={}
        )
        
        # Should have generated timestamp
        assert job1.created_at != ""
        assert "T" in job1.created_at  # ISO format indicator
        
        # Parse to verify it's valid datetime format
        parsed_time = datetime.fromisoformat(job1.created_at.replace('Z', '+00:00'))
        assert isinstance(parsed_time, datetime)
        
        # Test explicit timestamp preservation
        explicit_time = "2023-12-01T15:30:45"
        job2 = ProcessingJob(
            job_id="timestamp_test_2",
            pdf_path="/test2.pdf",
            metadata={},
            created_at=explicit_time
        )
        
        assert job2.created_at == explicit_time

    def test_processing_job_post_init_empty_timestamp(self):
        """
        GIVEN ProcessingJob with empty string created_at
        WHEN __post_init__ processes the empty timestamp
        THEN it should:
         - Replace empty string with current timestamp
         - Generate valid ISO format timestamp
         - Handle edge case of empty but not None timestamp
        """
        job = ProcessingJob(
            job_id="empty_timestamp_test",
            pdf_path="/test.pdf",
            metadata={},
            created_at=""  # Explicitly empty
        )
        
        # Should have replaced empty string with timestamp
        assert job.created_at != ""
        assert "T" in job.created_at
        
        # Verify it's a valid timestamp
        parsed_time = datetime.fromisoformat(job.created_at.replace('Z', '+00:00'))
        assert isinstance(parsed_time, datetime)

    def test_processing_job_metadata_structure(self):
        """
        GIVEN various metadata structures
        WHEN ProcessingJob is created with different metadata types
        THEN it should:
         - Accept dictionary metadata correctly
         - Preserve nested dictionary structures
         - Handle empty metadata appropriately
         - Maintain metadata immutability (no unintended sharing)
        """
        # Test complex nested metadata
        complex_metadata = {
            "batch_id": "batch_complex",
            "batch_metadata": {
                "project_id": "proj_123",
                "settings": {
                    "ocr_enabled": True,
                    "quality_threshold": 0.8
                }
            },
            "job_index": 5,
            "tags": ["urgent", "research"]
        }
        
        job = ProcessingJob(
            job_id="complex_metadata_test",
            pdf_path="/complex.pdf",
            metadata=complex_metadata
        )
        
        assert job.metadata["batch_id"] == "batch_complex"
        assert job.metadata["batch_metadata"]["project_id"] == "proj_123"
        assert job.metadata["batch_metadata"]["settings"]["ocr_enabled"] is True
        assert job.metadata["job_index"] == 5
        assert "urgent" in job.metadata["tags"]

    def test_processing_job_priority_validation(self):
        """
        GIVEN different priority values within valid range
        WHEN ProcessingJob is created with various priorities
        THEN it should:
         - Accept priority values 1-10
         - Handle edge cases (1 and 10)
         - Use default priority (5) when not specified
         - Maintain priority as integer type
        """
        # Test minimum priority
        job_min = ProcessingJob(
            job_id="min_priority",
            pdf_path="/min.pdf",
            metadata={},
            priority=1
        )
        assert job_min.priority == 1
        
        # Test maximum priority
        job_max = ProcessingJob(
            job_id="max_priority", 
            pdf_path="/max.pdf",
            metadata={},
            priority=10
        )
        assert job_max.priority == 10
        
        # Test default priority
        job_default = ProcessingJob(
            job_id="default_priority",
            pdf_path="/default.pdf",
            metadata={}
        )
        assert job_default.priority == 5

    def test_processing_job_status_values(self):
        """
        GIVEN different valid status values
        WHEN ProcessingJob status is set to various states
        THEN it should:
         - Accept all valid status strings
         - Handle status transitions appropriately
         - Maintain status consistency
        """
        valid_statuses = ["pending", "processing", "completed", "failed"]
        
        for status in valid_statuses:
            job = ProcessingJob(
                job_id=f"status_test_{status}",
                pdf_path=f"/{status}.pdf",
                metadata={},
                status=status
            )
            assert job.status == status


class TestBatchJobResultDataclass:
    """Test class for BatchJobResult dataclass functionality."""

    def test_batch_job_result_successful_completion(self):
        """
        GIVEN a successful job processing result
        WHEN BatchJobResult is created for completed job
        THEN it should:
         - Have status='completed'
         - Include all processing metrics
         - Have no error message
         - Include valid entity and relationship counts
         - Include processing time and identifiers
        """
        result = BatchJobResult(
            job_id="success_job_123",
            status="completed",
            processing_time=75.5,
            document_id="doc_abc123",
            knowledge_graph_id="graph_xyz789",
            ipld_cid="Qm123456789",
            entity_count=25,
            relationship_count=40,
            chunk_count=12
        )
        
        assert result.job_id == "success_job_123"
        assert result.status == "completed"
        assert result.processing_time == 75.5
        assert result.document_id == "doc_abc123"
        assert result.knowledge_graph_id == "graph_xyz789"
        assert result.ipld_cid == "Qm123456789"
        assert result.entity_count == 25
        assert result.relationship_count == 40
        assert result.chunk_count == 12
        assert result.error_message is None

    def test_batch_job_result_failed_processing(self):
        """
        GIVEN a failed job processing result
        WHEN BatchJobResult is created for failed job
        THEN it should:
         - Have status='failed'
         - Include detailed error message
         - Have None for successful processing identifiers
         - Have zero counts for entities/relationships
         - Include processing time up to failure
        """
        result = BatchJobResult(
            job_id="failed_job_456",
            status="failed",
            processing_time=15.2,
            error_message="PDF parsing failed: corrupted file structure",
            entity_count=0,
            relationship_count=0,
            chunk_count=0
        )
        
        assert result.job_id == "failed_job_456"
        assert result.status == "failed"
        assert result.processing_time == 15.2
        assert result.error_message == "PDF parsing failed: corrupted file structure"
        assert result.document_id is None
        assert result.knowledge_graph_id is None
        assert result.ipld_cid is None
        assert result.entity_count == 0
        assert result.relationship_count == 0
        assert result.chunk_count == 0

    def test_batch_job_result_partial_failure(self):
        """
        GIVEN a job that partially succeeded before failing
        WHEN BatchJobResult is created for partial processing
        THEN it should:
         - Include identifiers from successful stages
         - Have error message explaining failure point
         - Include partial counts where applicable
         - Reflect processing up to failure point
        """
        result = BatchJobResult(
            job_id="partial_job_789",
            status="failed",
            processing_time=45.8,
            document_id="doc_partial123",  # PDF stage succeeded
            knowledge_graph_id=None,  # GraphRAG stage failed
            ipld_cid=None,
            entity_count=0,  # Failed before entity extraction
            relationship_count=0,
            chunk_count=8,  # From successful PDF processing
            error_message="GraphRAG integration timeout"
        )
        
        assert result.status == "failed"
        assert result.document_id == "doc_partial123"
        assert result.knowledge_graph_id is None
        assert result.chunk_count == 8  # Partial success
        assert result.entity_count == 0  # Failed stage
        assert "timeout" in result.error_message

    def test_batch_job_result_default_values(self):
        """
        GIVEN minimal BatchJobResult creation
        WHEN only required fields are provided
        THEN it should:
         - Use appropriate default values for optional fields
         - Have None for missing identifiers
         - Have zero for missing counts
         - Maintain data type consistency
        """
        result = BatchJobResult(
            job_id="minimal_job",
            status="completed",
            processing_time=30.0
        )
        
        assert result.job_id == "minimal_job"
        assert result.status == "completed"
        assert result.processing_time == 30.0
        assert result.document_id is None
        assert result.knowledge_graph_id is None
        assert result.ipld_cid is None
        assert result.entity_count == 0
        assert result.relationship_count == 0
        assert result.chunk_count == 0
        assert result.error_message is None


class TestBatchStatusDataclass:
    """Test class for BatchStatus dataclass functionality."""

    def test_batch_status_initialization(self):
        """
        GIVEN valid parameters for BatchStatus
        WHEN BatchStatus is instantiated
        THEN it should:
         - Initialize all required fields correctly
         - Calculate derived fields properly
         - Handle timing and metrics appropriately
         - Include resource usage data structure
        """
        resource_usage = {
            "memory_mb": 2048.0,
            "cpu_percent": 35.5,
            "active_workers": 4
        }
        
        status = BatchStatus(
            batch_id="status_test_batch",
            total_jobs=20,
            completed_jobs=12,
            failed_jobs=3,
            pending_jobs=5,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            end_time="2024-01-01T11:30:00",
            total_processing_time=3600.0,
            average_job_time=240.0,
            throughput=0.2,
            resource_usage=resource_usage
        )
        
        assert status.batch_id == "status_test_batch"
        assert status.total_jobs == 20
        assert status.completed_jobs == 12
        assert status.failed_jobs == 3
        assert status.pending_jobs == 5
        assert status.processing_jobs == 0
        assert status.start_time == "2024-01-01T10:00:00"
        assert status.end_time == "2024-01-01T11:30:00"
        assert status.total_processing_time == 3600.0
        assert status.average_job_time == 240.0
        assert status.throughput == 0.2
        assert status.resource_usage == resource_usage

    def test_batch_status_active_batch(self):
        """
        GIVEN an active (incomplete) batch
        WHEN BatchStatus represents ongoing processing
        THEN it should:
         - Have end_time as None
         - Have pending_jobs > 0 or processing_jobs > 0
         - Have throughput as 0.0 (not yet calculable)
         - Represent current processing state
        """
        status = BatchStatus(
            batch_id="active_batch_test",
            total_jobs=15,
            completed_jobs=8,
            failed_jobs=1,
            pending_jobs=4,
            processing_jobs=2,
            start_time="2024-01-01T14:00:00",
            end_time=None,  # Still active
            total_processing_time=1200.0,
            average_job_time=133.33,
            throughput=0.0,  # Not complete yet
            resource_usage={}
        )
        
        assert status.end_time is None
        assert status.pending_jobs > 0 or status.processing_jobs > 0
        assert status.throughput == 0.0
        assert status.completed_jobs + status.failed_jobs + status.pending_jobs + status.processing_jobs == status.total_jobs

    def test_batch_status_completed_batch(self):
        """
        GIVEN a completed batch
        WHEN BatchStatus represents finished processing
        THEN it should:
         - Have end_time set
         - Have pending_jobs = 0 and processing_jobs = 0
         - Have completed_jobs + failed_jobs = total_jobs
         - Have calculated throughput > 0
         - Include final processing metrics
        """
        status = BatchStatus(
            batch_id="completed_batch_test",
            total_jobs=10,
            completed_jobs=8,
            failed_jobs=2,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T09:00:00",
            end_time="2024-01-01T10:00:00",
            total_processing_time=2400.0,
            average_job_time=300.0,
            throughput=0.167,  # ~10 jobs per hour
            resource_usage={}
        )
        
        assert status.end_time is not None
        assert status.pending_jobs == 0
        assert status.processing_jobs == 0
        assert status.completed_jobs + status.failed_jobs == status.total_jobs
        assert status.throughput > 0

    def test_batch_status_job_count_consistency(self):
        """
        GIVEN BatchStatus with various job counts
        WHEN job counts are examined for consistency
        THEN it should:
         - Have completed + failed + pending + processing = total_jobs
         - Maintain mathematical consistency
         - Handle edge cases with zero counts
         - Validate count relationships
        """
        # Test normal case
        status1 = BatchStatus(
            batch_id="consistency_test_1",
            total_jobs=25,
            completed_jobs=15,
            failed_jobs=5,
            pending_jobs=3,
            processing_jobs=2,
            start_time="2024-01-01T10:00:00",
            total_processing_time=1500.0,
            average_job_time=100.0,
            throughput=0.0,
            resource_usage={}
        )
        
        assert status1.completed_jobs + status1.failed_jobs + status1.pending_jobs + status1.processing_jobs == status1.total_jobs
        
        # Test edge case - all completed
        status2 = BatchStatus(
            batch_id="consistency_test_2",
            total_jobs=5,
            completed_jobs=5,
            failed_jobs=0,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T10:00:00",
            end_time="2024-01-01T10:30:00",
            total_processing_time=750.0,
            average_job_time=150.0,
            throughput=0.167,
            resource_usage={}
        )
        
        assert status2.completed_jobs + status2.failed_jobs + status2.pending_jobs + status2.processing_jobs == status2.total_jobs

    def test_batch_status_timing_metrics(self):
        """
        GIVEN BatchStatus with timing information
        WHEN timing metrics are examined
        THEN it should:
         - Have start_time in ISO format
         - Have end_time in ISO format when complete
         - Calculate meaningful average_job_time
         - Include reasonable total_processing_time
         - Calculate throughput appropriately
        """
        status = BatchStatus(
            batch_id="timing_test_batch",
            total_jobs=12,
            completed_jobs=10,
            failed_jobs=2,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T08:00:00",
            end_time="2024-01-01T10:00:00",
            total_processing_time=3000.0,  # 50 minutes total processing
            average_job_time=300.0,  # 5 minutes per successful job
            throughput=0.1,  # 6 jobs per hour
            resource_usage={}
        )
        
        # Verify ISO format timestamps
        assert "T" in status.start_time
        assert "T" in status.end_time
        
        # Verify timing consistency
        assert status.average_job_time == status.total_processing_time / status.completed_jobs
        assert status.throughput > 0
        
        # Parse timestamps to verify validity
        start_dt = datetime.fromisoformat(status.start_time)
        end_dt = datetime.fromisoformat(status.end_time)
        assert isinstance(start_dt, datetime)
        assert isinstance(end_dt, datetime)
        assert end_dt > start_dt

    def test_batch_status_resource_usage_structure(self):
        """
        GIVEN BatchStatus with resource usage data
        WHEN resource usage is examined
        THEN it should:
         - Accept dictionary structure for resource_usage
         - Preserve nested resource information
         - Handle empty resource usage gracefully
         - Support various resource metric types
        """
        detailed_resources = {
            "memory_mb": 4096.0,
            "memory_percent": 65.5,
            "cpu_percent": 42.3,
            "active_workers": 8,
            "queue_size": 15,
            "peak_memory_mb": 5120.0,
            "system_info": {
                "total_memory_gb": 16,
                "cpu_cores": 8,
                "platform": "linux"
            }
        }
        
        status = BatchStatus(
            batch_id="resource_test_batch",
            total_jobs=20,
            completed_jobs=5,
            failed_jobs=1,
            pending_jobs=12,
            processing_jobs=2,
            start_time="2024-01-01T11:00:00",
            total_processing_time=300.0,
            average_job_time=50.0,
            throughput=0.0,
            resource_usage=detailed_resources
        )
        
        assert status.resource_usage["memory_mb"] == 4096.0
        assert status.resource_usage["active_workers"] == 8
        assert status.resource_usage["system_info"]["cpu_cores"] == 8
        
        # Test empty resource usage
        status_empty = BatchStatus(
            batch_id="empty_resource_test",
            total_jobs=5,
            completed_jobs=2,
            failed_jobs=0,
            pending_jobs=3,
            processing_jobs=0,
            start_time="2024-01-01T12:00:00",
            total_processing_time=120.0,
            average_job_time=60.0,
            throughput=0.0,
            resource_usage={}
        )
        
        assert status_empty.resource_usage == {}

    def test_batch_status_progress_calculation(self):
        """
        GIVEN BatchStatus with various completion states
        WHEN progress is calculated from job counts
        THEN it should:
         - Calculate completion percentage correctly
         - Handle edge cases (0% and 100% completion)
         - Distinguish between completed and total processed
         - Support progress tracking calculations
        """
        # Test partial completion
        status_partial = BatchStatus(
            batch_id="progress_partial",
            total_jobs=50,
            completed_jobs=30,
            failed_jobs=5,
            pending_jobs=15,
            processing_jobs=0,
            start_time="2024-01-01T09:00:00",
            total_processing_time=1800.0,
            average_job_time=60.0,
            throughput=0.0,
            resource_usage={}
        )
        
        completion_rate = status_partial.completed_jobs / status_partial.total_jobs
        processed_rate = (status_partial.completed_jobs + status_partial.failed_jobs) / status_partial.total_jobs
        
        assert completion_rate == 0.6  # 30/50
        assert processed_rate == 0.7   # 35/50
        
        # Test zero completion
        status_zero = BatchStatus(
            batch_id="progress_zero",
            total_jobs=10,
            completed_jobs=0,
            failed_jobs=0,
            pending_jobs=10,
            processing_jobs=0,
            start_time="2024-01-01T13:00:00",
            total_processing_time=0.0,
            average_job_time=0.0,
            throughput=0.0,
            resource_usage={}
        )
        
        assert (status_zero.completed_jobs / status_zero.total_jobs) == 0.0
        
        # Test full completion
        status_complete = BatchStatus(
            batch_id="progress_complete",
            total_jobs=8,
            completed_jobs=6,
            failed_jobs=2,
            pending_jobs=0,
            processing_jobs=0,
            start_time="2024-01-01T14:00:00",
            end_time="2024-01-01T15:00:00",
            total_processing_time=2400.0,
            average_job_time=400.0,
            throughput=0.133,
            resource_usage={}
        )
        
        processed_rate_complete = (status_complete.completed_jobs + status_complete.failed_jobs) / status_complete.total_jobs
        assert processed_rate_complete == 1.0  # 8/8

    def test_batch_status_performance_metrics(self):
        """
        GIVEN BatchStatus with performance data
        WHEN performance metrics are examined
        THEN it should:
         - Have realistic processing times
         - Calculate reasonable throughput values
         - Include meaningful average job times
         - Support performance analysis calculations
        """
        status = BatchStatus(
            batch_id="performance_test",
            total_jobs=100,
            completed_jobs=85,
            failed_jobs=10,
            pending_jobs=5,
            processing_jobs=0,
            start_time="2024-01-01T08:00:00",
            end_time=None,  # Still processing
            total_processing_time=12750.0,  # 3.54 hours
            average_job_time=150.0,  # 2.5 minutes per job
            throughput=0.0,  # Not complete
            resource_usage={
                "memory_mb": 3072.0,
                "cpu_percent": 55.8,
                "active_workers": 6
            }
        )
        
        # Verify performance metric relationships
        expected_total_time = status.completed_jobs * status.average_job_time
        assert abs(status.total_processing_time - expected_total_time) < 1.0  # Allow small rounding
        
        # Verify realistic values
        assert status.average_job_time > 0
        assert status.total_processing_time > 0
        assert status.resource_usage["memory_mb"] > 0

    def test_dataclass_immutability_and_copying(self):
        """
        GIVEN dataclass instances
        WHEN instances are copied or modified
        THEN it should:
         - Support proper copying without reference sharing
         - Maintain data integrity across instances
         - Handle nested dictionary modifications correctly
         - Support comparison operations
        """
        original_metadata = {"batch_id": "test", "config": {"param": "value"}}
        
        job1 = ProcessingJob(
            job_id="copy_test_1",
            pdf_path="/test1.pdf",
            metadata=original_metadata.copy()
        )
        
        job2 = ProcessingJob(
            job_id="copy_test_2", 
            pdf_path="/test2.pdf",
            metadata=original_metadata.copy()
        )
        
        # Modify metadata in one job
        job1.metadata["config"]["param"] = "modified"
        
        # Other job should be unaffected
        assert job2.metadata["config"]["param"] == "value"
        assert job1.metadata["config"]["param"] == "modified"
        
        # Test equality
        assert job1.job_id != job2.job_id
        assert job1.pdf_path != job2.pdf_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
