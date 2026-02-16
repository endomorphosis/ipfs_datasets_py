"""Core infrastructure for the unified processors system.

This module provides the foundational components for the processor architecture:
- ProcessorProtocol: Interface that all processors must implement
- ProcessingContext: Context for processing operations
- ProcessingResult: Standardized result format
- InputType: Classification of input types
- InputDetector: Automatic input detection and classification
- ProcessorRegistry: Registration and discovery of processors
- UniversalProcessor: Single entry point for all processing operations
"""

from .protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
    Processor,
    is_processor,
)
from .input_detector import (
    InputDetector,
    detect_input,
    detect_format,
)
from .registry import (
    ProcessorRegistry,
    ProcessorEntry,
    get_global_registry,
)
from .universal_processor import (
    UniversalProcessor,
    get_universal_processor,
    process,
    process_batch,
)

__all__ = [
    'ProcessorProtocol',
    'Processor',
    'ProcessingContext',
    'ProcessingResult',
    'InputType',
    'is_processor',
    'InputDetector',
    'detect_input',
    'detect_format',
    'ProcessorRegistry',
    'ProcessorEntry',
    'get_global_registry',
    'UniversalProcessor',
    'get_universal_processor',
    'process',
    'process_batch',
]
