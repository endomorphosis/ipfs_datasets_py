"""
Unified File Converter for IPFS Datasets Python

Phase 1: Import and wrap existing libraries (omni_converter_mk2, convert_to_txt_based_on_mime_type)
Phase 2: Native reimplementation (format detection, extractors, async pipeline)
Phase 3: IPFS storage and ML acceleration integration

This module provides a single, clean API for file conversion while allowing
gradual migration from external libraries to native implementation.
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
]

__version__ = '0.3.1'  # Phase 3 - Enhanced with metadata and batch processing
