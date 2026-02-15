"""Core infrastructure for the unified processors system.

This module provides the foundational components for the processor architecture:
- ProcessorProtocol: Interface that all processors must implement
- ProcessingContext: Context for processing operations
- ProcessingResult: Standardized result format
- InputType: Classification of input types
- InputDetector: Automatic input detection and classification
- ProcessorRegistry: Registration and discovery of processors
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
from .processor_registry import (
    ProcessorRegistry,
    ProcessorEntry,
    get_global_registry,
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
]
