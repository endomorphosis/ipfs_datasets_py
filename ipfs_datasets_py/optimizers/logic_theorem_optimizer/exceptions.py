"""Logic theorem optimizer exceptions built on the common optimizer hierarchy."""

from __future__ import annotations

from ..common.exceptions import (
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
)


class LogicTheoremOptimizerError(OptimizerError):
    """Base class for logic theorem optimizer exceptions."""


__all__ = [
    "LogicTheoremOptimizerError",
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
]
