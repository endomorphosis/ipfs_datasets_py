"""Core infrastructure for the unified processors system.

This module provides the foundational components for the processor architecture:
- ProcessorProtocol: Interface that all processors must implement
- ProcessingContext: Context for processing operations
- ProcessingResult: Standardized result format
- InputType: Classification of input types
"""

from .protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
    Processor,
    is_processor,
)

__all__ = [
    'ProcessorProtocol',
    'Processor',
    'ProcessingContext',
    'ProcessingResult',
    'InputType',
    'is_processor',
]
