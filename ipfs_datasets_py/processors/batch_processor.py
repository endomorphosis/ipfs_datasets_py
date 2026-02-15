"""
DEPRECATED: Batch Processor module.

This module has been deprecated and moved to processors.specialized.batch.

.. deprecated:: 1.9.0
   This module is deprecated. Use BatchProcessor from 
   processors.specialized.batch instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.batch_processor import BatchProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.batch import BatchProcessor
        
    Or use the adapter:
        from ipfs_datasets_py.processors.adapters import BatchAdapter

For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.batch_processor is deprecated. "
    "Use processors.specialized.batch.BatchProcessor instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.batch import (
        BatchProcessor,
        ProcessingJob,
        BatchJobResult,
        BatchStatus,
    )
except ImportError:
    # If specialized.batch is not available, create stubs
    class BatchProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "BatchProcessor requires dependencies that are not installed."
            )
    
    class ProcessingJob:
        pass
    
    class BatchJobResult:
        pass
    
    class BatchStatus:
        pass

__all__ = [
    'BatchProcessor',
    'ProcessingJob',
    'BatchJobResult',
    'BatchStatus',
]
