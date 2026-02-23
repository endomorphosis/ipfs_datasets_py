"""GraphRAG-specific exceptions built on the common optimizer hierarchy."""

from __future__ import annotations

from ..common.exceptions import (
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
)


class GraphRAGError(OptimizerError):
    """Base class for GraphRAG-specific exceptions."""


__all__ = [
    "GraphRAGError",
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
]
