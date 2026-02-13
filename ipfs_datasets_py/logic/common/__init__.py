"""
Common utilities and patterns for the logic module.

This package provides shared utilities that are used across multiple logic
submodules to reduce code duplication and standardize common patterns.

Created during Phase 2 - Quality Improvements.
"""

from .errors import (
    LogicError,
    ConversionError,
    ValidationError,
    ProofError,
    TranslationError,
    BridgeError,
    ConfigurationError,
    DeonticError,
    ModalError,
    TemporalError,
)

from .converters import (
    LogicConverter,
    ChainedConverter,
    ConversionResult,
    ConversionStatus,
    ValidationResult,
)

__all__ = [
    # Error classes
    "LogicError",
    "ConversionError",
    "ValidationError",
    "ProofError",
    "TranslationError",
    "BridgeError",
    "ConfigurationError",
    "DeonticError",
    "ModalError",
    "TemporalError",
    # Converter classes
    "LogicConverter",
    "ChainedConverter",
    "ConversionResult",
    "ConversionStatus",
    "ValidationResult",
]
