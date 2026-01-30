"""
Unified File Converter for IPFS Datasets Python

Phase 1: Import and wrap existing libraries (omni_converter_mk2, convert_to_txt_based_on_mime_type)
Phase 2: Native reimplementation (format detection, extractors, async pipeline)

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
]

__version__ = '0.2.0'  # Phase 2 - Native Implementation (Features 1-3)
