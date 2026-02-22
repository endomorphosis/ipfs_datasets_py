"""Typed exception hierarchy for all optimizer types.

Defines a tree of exceptions that concrete optimizers should raise in
preference to bare ``Exception`` or ``RuntimeError``.  Catching the base
class ``OptimizerError`` will catch any optimizer-related exception.

Exception tree::

    OptimizerError
    ├── ExtractionError       – failure during artifact generation / NER
    ├── ValidationError       – artifact fails validation (syntax, logic, schema)
    │   └── ProvingError      – theorem prover returned UNSAT / error
    ├── RefinementError       – mediator/optimizer refinement step failed
    └── ConfigurationError    – bad optimizer configuration

Usage::

    from ipfs_datasets_py.optimizers.common.exceptions import (
        OptimizerError, ExtractionError, ValidationError,
        ProvingError, RefinementError, ConfigurationError,
    )

    try:
        result = optimizer.run_session(data, context)
    except ProvingError as e:
        logger.warning(f"Prover failed: {e}")
    except ValidationError as e:
        logger.error(f"Validation failed: {e}")
    except OptimizerError as e:
        logger.error(f"Optimizer error: {e}")
"""

from __future__ import annotations

from typing import Any, Optional


class OptimizerError(Exception):
    """Base class for all optimizer-related exceptions.

    Args:
        message: Human-readable description of the error.
        details: Optional structured details (dict, list, …).
    """

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} | details={self.details!r}"
        return self.message


class ExtractionError(OptimizerError):
    """Raised when artifact extraction / NER / generation fails.

    Examples:
        - Rule-based extractor encounters malformed input
        - LLM backend returns an error or empty response
        - NER pipeline raises an unexpected exception
    """


class ValidationError(OptimizerError):
    """Raised when an artifact fails structural or semantic validation.

    Examples:
        - Ontology has dangling entity references
        - Generated code fails syntax check
        - Required schema fields are missing

    Attributes:
        errors: List of validation error messages.
    """

    def __init__(
        self,
        message: str,
        errors: Optional[list[str]] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message, details=details)
        self.errors: list[str] = list(errors or [])

    def __str__(self) -> str:
        base = super().__str__()
        if self.errors:
            return f"{base} | errors={self.errors}"
        return base


class ProvingError(ValidationError):
    """Raised when a theorem prover returns UNSAT or encounters an error.

    This is a subclass of :class:`ValidationError` because a failed proof
    is a form of validation failure.

    Attributes:
        prover: Name of the prover that failed (e.g. ``"z3"``).
        formula: The formula that could not be proved (if available).
    """

    def __init__(
        self,
        message: str,
        prover: Optional[str] = None,
        formula: Optional[str] = None,
        errors: Optional[list[str]] = None,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message, errors=errors, details=details)
        self.prover = prover
        self.formula = formula

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.prover:
            parts.append(f"prover={self.prover!r}")
        if self.formula:
            parts.append(f"formula={self.formula!r}")
        return " | ".join(parts)


class RefinementError(OptimizerError):
    """Raised when an optimizer/mediator refinement step fails unexpectedly.

    Examples:
        - Mediator ``refine_ontology()`` produces an invalid ontology
        - SGD optimizer diverges (infinite loop / NaN score)
        - Refinement action raises an unhandled exception
    """


class ConfigurationError(OptimizerError):
    """Raised when the optimizer is mis-configured.

    Examples:
        - Required config key is missing
        - Invalid strategy value
        - Incompatible combination of options
    """


__all__ = [
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
]
