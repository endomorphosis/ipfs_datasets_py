"""Agentic optimizer exceptions built on the common optimizer hierarchy."""

from __future__ import annotations

from ..common.exceptions import (
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
)


class AgenticError(OptimizerError):
    """Base class for agentic optimizer exceptions."""


__all__ = [
    "AgenticError",
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
]
