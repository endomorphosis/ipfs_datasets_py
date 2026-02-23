"""Logic optimizer exceptions built on the common optimizer hierarchy."""

from __future__ import annotations

from ..common.exceptions import (
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
)


class LogicError(OptimizerError):
    """Base class for logic optimizer exceptions."""


__all__ = [
    "LogicError",
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
]
