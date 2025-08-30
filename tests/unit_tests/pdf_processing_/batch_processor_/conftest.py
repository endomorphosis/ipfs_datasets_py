"""
Pytest configuration and shared fixtures for batch processor tests.

This module provides common fixtures and test utilities for all batch processor
test modules. Fixtures defined here are automatically available to all test files
in this directory and subdirectories.
"""

import pytest
from unittest.mock import MagicMock
from ipfs_datasets_py.pdf_processing.batch_processor import BatchProcessor
from ipfs_datasets_py.ipld.storage import IPLDStorage
from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator

# Test configuration constants
DEFAULT_MAX_WORKERS = 4
DEFAULT_MAX_MEMORY_MB = 2048
MIN_MEMORY_MB = 512
MIN_WORKERS = 1
MAX_WORKERS_CUSTOM = 12
MAX_WORKERS_HIGH = 16
MAX_MEMORY_CUSTOM = 8192
SAMPLE_BATCH_SIZE = 5
SUCCESSFUL_JOBS_COUNT = 3
FAILED_JOBS_COUNT = 2
PENDING_JOBS_COUNT = 4
PROCESSING_TIME_FAST = 30.0
PROCESSING_TIME_MEDIUM = 75.5
PROCESSING_TIME_SLOW = 150.0
ENTITY_COUNT_SMALL = 15
ENTITY_COUNT_MEDIUM = 22
ENTITY_COUNT_LARGE = 25
RELATIONSHIP_COUNT_SMALL = 25
RELATIONSHIP_COUNT_MEDIUM = 35
RELATIONSHIP_COUNT_LARGE = 40
CHUNK_COUNT_SMALL = 8
CHUNK_COUNT_MEDIUM = 10
CHUNK_COUNT_LARGE = 12
DEFAULT_PRIORITY = 5
HIGH_PRIORITY = 8
LOW_PRIORITY = 1
MAX_PRIORITY = 10


@pytest.fixture
def mock_storage():
    """Create a mock storage instance for testing."""
    return MagicMock(spec_set=IPLDStorage)


@pytest.fixture  
def mock_pdf_processor():
    """Create a mock PDF processor for testing."""
    return MagicMock(spec_set=PDFProcessor)


@pytest.fixture
def mock_llm_optimizer():
    """Create a mock LLM optimizer for testing."""
    return MagicMock(spec_set=LLMOptimizer)


@pytest.fixture
def mock_graphrag_integrator():
    """Create a mock GraphRAG integrator for testing.""" 
    return MagicMock(spec_set=GraphRAGIntegrator)

@pytest.fixture
def successful_processing_results():
    """Create mock successful processing results for testing."""
    return {
        'processed_files': ['file1.pdf', 'file2.pdf', 'file3.pdf'],
        'failed_files': [],
        'total_processed': SUCCESSFUL_JOBS_COUNT,
        'total_failed': 0,
        'processing_time': PROCESSING_TIME_MEDIUM,
        'memory_used_mb': MIN_MEMORY_MB,
        'ipfs_hashes': ['QmHash1', 'QmHash2', 'QmHash3']
    }


@pytest.fixture
def failed_processing_results():
    """Create mock failed processing results for testing."""
    return {
        'processed_files': [],
        'failed_files': ['corrupted.pdf', 'locked.pdf'],
        'total_processed': 0,
        'total_failed': FAILED_JOBS_COUNT,
        'processing_time': PROCESSING_TIME_FAST,
        'memory_used_mb': 128,
        'ipfs_hashes': [],
        'errors': ['File corrupted', 'Permission denied']
    }


@pytest.fixture
def mixed_processing_results():
    """Create mock mixed processing results for testing."""
    return {
        'processed_files': ['success1.pdf', 'success2.pdf'],
        'failed_files': ['failed.pdf'],
        'total_processed': FAILED_JOBS_COUNT,
        'total_failed': MIN_WORKERS,
        'processing_time': 78.5,
        'memory_used_mb': 896,
        'ipfs_hashes': ['QmHashA', 'QmHashB'],
        'errors': ['Timeout error']
    }


@pytest.fixture
def mock_successful_processor(processor, successful_processing_results):
    """Configure processor to return successful results."""
    processor.process_batch.return_value = successful_processing_results
    processor.process_files.return_value = successful_processing_results
    return processor


@pytest.fixture
def mock_failed_processor(processor, failed_processing_results):
    """Configure processor to return failed results."""
    processor.process_batch.return_value = failed_processing_results
    processor.process_files.return_value = failed_processing_results
    return processor

@pytest.fixture
def processor(mock_storage, mock_pdf_processor, mock_llm_optimizer, mock_graphrag_integrator):
    """Create a BatchProcessor instance with all dependencies mocked.
    
    This fixture provides a fully configured BatchProcessor instance with all
    external dependencies replaced by mocks. It's suitable for integration tests
    that focus on BatchProcessor logic without testing the actual processing components.
    
    Returns:
        BatchProcessor: Instance with mocked dependencies and standard test configuration.
    """
    processor = BatchProcessor(
        max_workers=DEFAULT_MAX_WORKERS,
        max_memory_mb=DEFAULT_MAX_MEMORY_MB,
        storage=mock_storage,
        pdf_processor=mock_pdf_processor,
        llm_optimizer=mock_llm_optimizer,
        graphrag_integrator=mock_graphrag_integrator
    )
    
    return processor


@pytest.fixture
def processor_with_custom_config(mock_storage, mock_pdf_processor, mock_llm_optimizer, mock_graphrag_integrator):
    """Create a BatchProcessor instance with custom configuration for specific tests.
    
    This fixture allows tests to easily create processors with different configurations
    while still having mocked dependencies.
    
    Returns:
        callable: Function that creates BatchProcessor with custom parameters.
    """
    def _create_processor(**kwargs):
        # Set defaults
        config = {
            'max_workers': DEFAULT_MAX_WORKERS,
            'max_memory_mb': DEFAULT_MAX_MEMORY_MB,
            'storage': mock_storage,
            'pdf_processor': mock_pdf_processor,
            'llm_optimizer': mock_llm_optimizer,
            'graphrag_integrator': mock_graphrag_integrator
        }
        # Override with provided kwargs
        config.update(kwargs)
        
        processor = BatchProcessor(**config)
        
        return processor
    
    return _create_processor

# Data class fixtures
@pytest.fixture
def successful_job_result():
    """Create a successful BatchJobResult for testing."""
    from ipfs_datasets_py.pdf_processing.batch_processor import BatchJobResult
    return BatchJobResult(
        job_id="success_job_123",
        status="completed",
        processing_time=PROCESSING_TIME_MEDIUM,
        document_id="doc_abc123",
        knowledge_graph_id="graph_xyz789",
        ipld_cid="Qm123456789",
        entity_count=ENTITY_COUNT_LARGE,
        relationship_count=RELATIONSHIP_COUNT_LARGE,
        chunk_count=CHUNK_COUNT_LARGE
    )

@pytest.fixture
def failed_job_result():
    """Create a failed BatchJobResult for testing."""
    from ipfs_datasets_py.pdf_processing.batch_processor import BatchJobResult
    return BatchJobResult(
        job_id="failed_job_456",
        status="failed",
        processing_time=PROCESSING_TIME_FAST,
        error_message="PDF parsing failed: corrupted file structure",
        entity_count=0,
        relationship_count=0,
        chunk_count=0
    )

@pytest.fixture
def batch_status_active():
    """Create an active BatchStatus for testing."""
    from ipfs_datasets_py.pdf_processing.batch_processor import BatchStatus
    return BatchStatus(
        batch_id="active_batch_test",
        total_jobs=15,
        completed_jobs=8,
        failed_jobs=1,
        pending_jobs=PENDING_JOBS_COUNT,
        processing_jobs=FAILED_JOBS_COUNT,
        start_time="2024-01-01T14:00:00",
        end_time=None,
        total_processing_time=1200.0,
        average_job_time=133.33,
        throughput=0.0,
        resource_usage={}
    )

@pytest.fixture
def batch_status_completed():
    """Create a completed BatchStatus for testing."""
    from ipfs_datasets_py.pdf_processing.batch_processor import BatchStatus
    return BatchStatus(
        batch_id="completed_batch_test",
        total_jobs=10,
        completed_jobs=8,
        failed_jobs=FAILED_JOBS_COUNT,
        pending_jobs=0,
        processing_jobs=0,
        start_time="2024-01-01T09:00:00",
        end_time="2024-01-01T10:00:00",
        total_processing_time=2400.0,
        average_job_time=300.0,
        throughput=0.167,
        resource_usage={}
    )

@pytest.fixture
def processing_job_basic():
    """Create a basic ProcessingJob for testing."""
    from ipfs_datasets_py.pdf_processing.batch_processor import ProcessingJob
    return ProcessingJob(
        job_id="test_job_123",
        pdf_path="/path/to/document.pdf",
        metadata={"batch_id": "batch_abc", "project": "test_project"}
    )

@pytest.fixture
def processing_job_custom():
    """Create a custom ProcessingJob for testing."""
    from ipfs_datasets_py.pdf_processing.batch_processor import ProcessingJob
    return ProcessingJob(
        job_id="custom_job_456",
        pdf_path="/custom/path/doc.pdf",
        metadata={
            "batch_id": "custom_batch",
            "user_id": "user_123",
            "tags": ["research", "analysis"]
        },
        priority=HIGH_PRIORITY,
        status="processing",
        error_message="Custom error",
        result={"doc_id": "doc_789"},
        processing_time=125.5,
        created_at="2024-01-01T12:00:00"
    )

@pytest.fixture 
def sample_pdf_files():
    """Create temporary PDF files for testing."""
    import tempfile
    with tempfile.TemporaryDirectory() as temp_dir:
        from pathlib import Path
        pdf_paths = []
        for i in range(SUCCESSFUL_JOBS_COUNT):
            pdf_path = Path(temp_dir) / f"document_{i}.pdf"
            pdf_path.write_text(f"Mock PDF content {i}")
            pdf_paths.append(str(pdf_path))
        yield pdf_paths

@pytest.fixture
def mock_batch_processor_dependencies():
    """Context manager for mocking BatchProcessor dependencies."""
    from unittest.mock import Mock, patch
    import contextlib
    
    @contextlib.contextmanager
    def _mock_dependencies():
        with patch('ipfs_datasets_py.pdf_processing.batch_processor.IPLDStorage') as mock_storage_class:
            with patch('ipfs_datasets_py.pdf_processing.batch_processor.PDFProcessor') as mock_pdf_class:
                with patch('ipfs_datasets_py.pdf_processing.batch_processor.LLMOptimizer') as mock_llm_class:
                    with patch('ipfs_datasets_py.pdf_processing.batch_processor.GraphRAGIntegrator') as mock_graphrag_class:
                        mock_storage_class.return_value = Mock()
                        mock_pdf_class.return_value = Mock()
                        mock_llm_class.return_value = Mock()
                        mock_graphrag_class.return_value = Mock()
                        yield
    
    return _mock_dependencies

@pytest.fixture
def sample_batch_with_results(processor):
    """Create a batch with completed and failed job results."""
    from ipfs_datasets_py.pdf_processing.batch_processor import BatchStatus, BatchJobResult
    
    batch_id = "batch_sample_123"
    
    # Create batch status
    batch_status = BatchStatus(
        batch_id=batch_id,
        total_jobs=SAMPLE_BATCH_SIZE,
        completed_jobs=SUCCESSFUL_JOBS_COUNT,
        failed_jobs=FAILED_JOBS_COUNT,
        pending_jobs=0,
        processing_jobs=0,
        start_time="2024-01-01T10:00:00",
        end_time="2024-01-01T10:30:00",
        total_processing_time=450.0,
        average_job_time=PROCESSING_TIME_SLOW,
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
            entity_count=ENTITY_COUNT_SMALL,
            relationship_count=RELATIONSHIP_COUNT_SMALL,
            chunk_count=CHUNK_COUNT_SMALL
        ),
        BatchJobResult(
            job_id="batch_sample_123_job_0002", 
            status='completed',
            processing_time=180.0,
            document_id="doc_2",
            knowledge_graph_id="graph_2",
            ipld_cid="cid_2",
            entity_count=ENTITY_COUNT_MEDIUM,
            relationship_count=RELATIONSHIP_COUNT_MEDIUM,
            chunk_count=CHUNK_COUNT_LARGE
        ),
        BatchJobResult(
            job_id="batch_sample_123_job_0003",
            status='completed', 
            processing_time=PROCESSING_TIME_SLOW,
            document_id="doc_3",
            knowledge_graph_id="graph_3",
            ipld_cid="cid_3",
            entity_count=18,
            relationship_count=28,
            chunk_count=CHUNK_COUNT_MEDIUM
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
            processing_time=PROCESSING_TIME_FAST,
            error_message="Memory exhausted during processing",
            entity_count=0,
            relationship_count=0,
            chunk_count=0
        )
    ]
    
    # Store results in the batch_results structure
    processor.batch_results[batch_id] = {
        'completed': completed_results,
        'failed': failed_results
    }
    
    return batch_id, batch_status, completed_results, failed_results
