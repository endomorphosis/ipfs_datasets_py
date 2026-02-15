"""Core infrastructure for the unified processors system.

This module provides the foundational components for the processor architecture:
- ProcessorProtocol: Interface that all processors must implement
- ProcessingContext: Context for processing operations
- ProcessingResult: Standardized result format
- InputType: Classification of input types
- InputDetector: Automatic input detection and classification
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
]
