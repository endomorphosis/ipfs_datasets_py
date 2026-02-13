"""
Common Error Hierarchy for Logic Module

This module provides a standardized error hierarchy for the logic module,
replacing inconsistent use of ValueError, TypeError, and RuntimeError with
domain-specific exceptions that provide better error messages and context.

Created during Phase 2 - Quality Improvements to unify error handling patterns.
"""

from typing import Optional, Dict, Any


class LogicError(Exception):
    """Base exception for all logic module errors."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        """
        Initialize LogicError with message and optional context.
        
        Args:
            message: Human-readable error message
            context: Optional dictionary with error context for debugging
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}
    
    def __str__(self) -> str:
        """Return formatted error message with context if available."""
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} (Context: {context_str})"
        return self.message


class ConversionError(LogicError):
    """Raised when logic conversion fails."""
    pass


class ValidationError(LogicError):
    """Raised when validation fails."""
    pass


class ProofError(LogicError):
    """Raised when proof execution fails."""
    pass


class TranslationError(LogicError):
    """Raised when logic translation fails."""
    pass


class BridgeError(LogicError):
    """Raised when prover bridge operation fails."""
    pass


class ConfigurationError(LogicError):
    """Raised when configuration is invalid."""
    pass


class DeonticError(LogicError):
    """Raised when deontic logic operation fails."""
    pass


class ModalError(LogicError):
    """Raised when modal logic operation fails."""
    pass


class TemporalError(LogicError):
    """Raised when temporal logic operation fails."""
    pass


__all__ = [
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
]
