"""
Batch Processing - Specialized batch processing functionality.

This package provides comprehensive batch processing capabilities:
- Parallel job execution
- Queue management
- Resource limits and throttling
- Progress tracking
- Result aggregation

Main Classes:
- BatchProcessor: Main batch processor with job queue
- ProcessingJob: Job data structure
- BatchStatus: Batch status tracking
- BatchJobResult: Job result data structure

Example:
    from ipfs_datasets_py.processors.specialized.batch import BatchProcessor
    
    processor = BatchProcessor()
    result = processor.process_batch(jobs)
"""

try:
    from .processor import (
        BatchProcessor,
        ProcessingJob,
        BatchJobResult,
        BatchStatus,
    )
    _processor_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"Batch processor unavailable: {e}", ImportWarning)
    BatchProcessor = None
    ProcessingJob = None
    BatchJobResult = None
    BatchStatus = None
    _processor_available = False

try:
    from .file_converter_batch import (
        BatchProgress,
        ResourceLimits,
        CacheManager,
    )
    _file_converter_available = True
except ImportError as e:
    import warnings
    warnings.warn(f"File converter batch processor unavailable: {e}", ImportWarning)
    BatchProgress = None
    ResourceLimits = None
    CacheManager = None
    _file_converter_available = False

__all__ = [
    'BatchProcessor',
    'ProcessingJob',
    'BatchJobResult',
    'BatchStatus',
    'BatchProgress',
    'ResourceLimits',
    'CacheManager',
]
