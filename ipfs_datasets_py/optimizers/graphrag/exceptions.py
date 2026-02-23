"""GraphRAG-specific exceptions built on the common optimizer hierarchy."""

from __future__ import annotations

from typing import Any, Optional

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


class OntologyExtractionError(ExtractionError):
    """Raised when ontology extraction fails (rules or LLM)."""


class OntologyValidationError(ValidationError):
    """Raised when ontology validation detects structural or semantic issues.
    
    Examples:
        - Dangling entity references in relationships
        - Missing required fields (id, type, description)
        - Invalid threshold values
    """


class LogicProvingError(ProvingError):
    """Raised when logic prover detects contradictions or errors.
    
    Examples:
        - Z3 returns UNSAT for ontology axioms
        - Reasoner detects inconsistent entity types
    """


class PathResolutionError(ConfigurationError):
    """Raised when file path resolution or validation fails.
    
    Examples:
        - Path resolves outside allowed boundaries
        - Required file does not exist
        - Path contains invalid characters
    """


class QueryCacheError(OptimizerError):
    """Raised when query cache operations fail.
    
    Examples:
        - Cache entry expired or missing
        - Invalid cache format
        - Race condition on cache access
    """


class SessionError(RefinementError):
    """Raised when optimization session state is invalid.
    
    Examples:
        - Session not initialized before use
        - Invalid round number or state transition
        - Session failed to produce valid result
    """


__all__ = [
    "GraphRAGError",
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
    # GraphRAG-specific
    "OntologyExtractionError",
    "OntologyValidationError",
    "LogicProvingError",
    "PathResolutionError",
    "QueryCacheError",
    "SessionError",
]
