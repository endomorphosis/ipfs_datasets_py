"""
Unified File Converter for IPFS Datasets Python

Phase 1: Import and wrap existing libraries (omni_converter_mk2, convert_to_txt_based_on_mime_type)
Phase 2: Native reimplementation (format detection, extractors, async pipeline)
Phase 3: IPFS storage and ML acceleration integration

This module provides a single, clean API for file conversion while allowing
gradual migration from external libraries to native implementation.

MIGRATION NOTICE:
The markitdown and omni backends are deprecated. Please use the native backend instead:
  FileConverter(backend='native')

See docs/FILE_CONVERSION_INTEGRATION_PLAN.md for migration guide.
"""

from .converter import FileConverter, ConversionResult
from .pipeline import (
    Result, Error, ErrorType, Outcome,
    ok, error, wrap_exception,
    FileUnit, Pipeline, StreamProcessor,
    validate_file_exists, detect_format, extract_text
)
from .format_detector import FormatDetector, detect_format as detect_file_format
from .text_extractors import ExtractorRegistry, ExtractionResult, extract_text as extract_file_text
from .errors import (
    FileConversionError, ErrorHandler, FallbackStrategy,
    with_fallback, retry_with_backoff, ignore_errors, aggregate_errors
)

# Phase 3: IPFS and Acceleration integration
from .backends.ipfs_backend import IPFSBackend, get_ipfs_backend, IPFS_AVAILABLE
from .ipfs_accelerate_converter import (
    IPFSAcceleratedConverter,
    IPFSConversionResult,
    create_converter
)

# Advanced features: Metadata and Batch Processing
from .metadata_extractor import MetadataExtractor, extract_metadata
from .batch_processor import (
    BatchProcessor, BatchProgress, ResourceLimits, CacheManager,
    create_batch_processor
)

# Deprecation utilities
from .deprecation import (
    warn_deprecated_backend,
    get_deprecation_info,
    is_deprecated,
    DEPRECATION_TIMELINE
)

# Knowledge Graph and RAG Integration (Phase 4)
from .knowledge_graph_integration import (
    UniversalKnowledgeGraphPipeline,
    TextSummarizationPipeline,
    BatchKnowledgeGraphProcessor,
    KnowledgeGraphResult,
    TextSummaryResult
)

# Vector Embedding Integration (Phase 5)
from .vector_embedding_integration import (
    VectorEmbeddingPipeline,
    VectorEmbeddingResult,
    SearchResult,
    create_vector_pipeline
)

# Archive Handling (Phase 6)
from .archive_handler import (
    ArchiveHandler,
    ArchiveExtractionResult,
    extract_archive,
    is_archive
)

__all__ = [
    # Main API (Phase 1)
    'FileConverter', 
    'ConversionResult',
    
    # Pipeline API (Phase 2)
    'Result', 'Error', 'ErrorType', 'Outcome',
    'ok', 'error', 'wrap_exception',
    'FileUnit', 'Pipeline', 'StreamProcessor',
    'validate_file_exists', 'detect_format', 'extract_text',
    
    # Native components (Phase 2)
    'FormatDetector', 'detect_file_format',
    'ExtractorRegistry', 'ExtractionResult', 'extract_file_text',
    
    # Error handling (Phase 2 Feature 4)
    'FileConversionError', 'ErrorHandler', 'FallbackStrategy',
    'with_fallback', 'retry_with_backoff', 'ignore_errors', 'aggregate_errors',
    
    # IPFS integration (Phase 3)
    'IPFSBackend', 'get_ipfs_backend', 'IPFS_AVAILABLE',
    'IPFSAcceleratedConverter', 'IPFSConversionResult', 'create_converter',
    
    # Advanced features (Phase 3 continued)
    'MetadataExtractor', 'extract_metadata',
    'BatchProcessor', 'BatchProgress', 'ResourceLimits', 'CacheManager',
    'create_batch_processor',
    
    # Deprecation utilities
    'warn_deprecated_backend', 'get_deprecation_info', 'is_deprecated',
    'DEPRECATION_TIMELINE',
    
    # Knowledge Graph and RAG Integration (Phase 4)
    'UniversalKnowledgeGraphPipeline',
    'TextSummarizationPipeline',
    'BatchKnowledgeGraphProcessor',
    'KnowledgeGraphResult',
    'TextSummaryResult',
    
    # Vector Embedding Integration (Phase 5)
    'VectorEmbeddingPipeline',
    'VectorEmbeddingResult',
    'SearchResult',
    'create_vector_pipeline',
    
    # Archive Handling (Phase 6)
    'ArchiveHandler',
    'ArchiveExtractionResult',
    'extract_archive',
    'is_archive',
]

__version__ = '0.6.1'  # Phase 6.1 - Archive handling
