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
        wrap_exceptions, format_validation_errors,
    )

    # Basic usage
    try:
        result = optimizer.run_session(data, context)
    except ProvingError as e:
        logger.warning(f"Prover failed: {e}")
    except ValidationError as e:
        logger.error(f"Validation failed: {e}")
    except OptimizerError as e:
        logger.error(f"Optimizer error: {e}")
    
    # Using context managers
    with wrap_exceptions(ExtractionError, "Entity extraction failed"):
        entities = extract_entities(text)
"""

from __future__ import annotations

import functools
import logging
from contextlib import contextmanager
from typing import Any, Callable, Generator, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


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


# ============================================================================
# Exception Handling Utilities
# ============================================================================


def format_validation_errors(errors: list[str], max_errors: int = 5) -> str:
    """Format a list of validation errors as a human-readable string.
    
    Args:
        errors: List of validation error messages
        max_errors: Maximum number of errors to include in output
        
    Returns:
        Formatted string with errors numbered and truncated if needed
        
    Example:
        >>> errors = ["Missing field: id", "Invalid type: foo", "Bad value: -1"]
        >>> print(format_validation_errors(errors))
        3 validation errors:
          1. Missing field: id
          2. Invalid type: foo
          3. Bad value: -1
    """
    if not errors:
        return "No validation errors"
    
    count = len(errors)
    shown = errors[:max_errors]
    
    lines = [f"{count} validation error{'s' if count != 1 else ''}:"]
    for i, error in enumerate(shown, 1):
        lines.append(f"  {i}. {error}")
    
    if count > max_errors:
        lines.append(f"  ... and {count - max_errors} more")
    
    return "\n".join(lines)


@contextmanager
def wrap_exceptions(
    exception_class: Type[OptimizerError],
    message: str,
    details: Optional[Any] = None,
    reraise: bool = True,
) -> Generator[None, None, None]:
    """Context manager that wraps any exception as a typed OptimizerError.
    
    Args:
        exception_class: The OptimizerError subclass to raise
        message: Error message for the wrapped exception
        details: Optional additional context
        reraise: If True, sets original exception as __cause__
        
    Yields:
        None
        
    Raises:
        exception_class: If any exception occurs in the context
        
    Example:
        >>> with wrap_exceptions(ExtractionError, "Failed to extract entities"):
        ...     entities = extract_from_text(text)  # might raise any exception
    """
    try:
        yield
    except OptimizerError:
        # Already an optimizer error, re-raise as-is
        raise
    except Exception as e:
        # Intentional broad catch: this helper is specifically for wrapping
        # arbitrary non-base exceptions into typed OptimizerError classes.
        wrapped = exception_class(message, details=details)
        if reraise:
            raise wrapped from e
        else:
            raise wrapped


def exception_to_dict(exc: BaseException) -> dict[str, Any]:
    """Convert an exception to a dictionary for serialization.
    
    Args:
        exc: Any exception instance
        
    Returns:
        Dictionary with exception type, message, and details
        
    Example:
        >>> err = ValidationError("Schema invalid", errors=["Missing id"])
        >>> exception_to_dict(err)
        {'type': 'ValidationError', 'message': 'Schema invalid', 'errors': ['Missing id']}
    """
    # Use raw message for OptimizerError (not str() which includes details)
    message = exc.message if isinstance(exc, OptimizerError) else str(exc)
    
    result: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": message,
    }
    
    # Add OptimizerError-specific fields if present
    if isinstance(exc, OptimizerError):
        if exc.details is not None:
            result["details"] = exc.details
        if isinstance(exc, ValidationError) and exc.errors:
            result["errors"] = exc.errors
        if isinstance(exc, ProvingError):
            if exc.prover:
                result["prover"] = exc.prover
            if exc.formula:
                result["formula"] = exc.formula
    
    # Include cause chain if present
    if exc.__cause__:
        result["cause"] = exception_to_dict(exc.__cause__)
    
    return result


def safe_error_handler(
    *exception_types: Type[Exception],
    default: Any = None,
    log_level: int = logging.WARNING,
) -> Callable[[F], F]:
    """Decorator that catches specific exceptions and returns a default value.
    
    Useful for making non-critical operations fault-tolerant.
    
    Args:
        *exception_types: Exception types to catch (default: Exception)
        default: Value to return if exception is caught
        log_level: Logging level for caught exceptions
        
    Returns:
        Decorator function
        
    Example:
        >>> @safe_error_handler(ValueError, KeyError, default=[])
        ... def get_entities(data):
        ...     return data["entities"]  # might raise KeyError
        >>> get_entities({})  # Returns [] instead of raising
        []
    """
    if not exception_types:
        exception_types = (Exception,)
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except exception_types as e:
                logger.log(
                    log_level,
                    f"{func.__name__} raised {type(e).__name__}: {e}; returning default={default!r}"
                )
                return default
        return wrapper  # type: ignore
    return decorator


__all__ = [
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
    # Utilities
    "format_validation_errors",
    "wrap_exceptions",
    "exception_to_dict",
    "safe_error_handler",
]
