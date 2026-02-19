"""
Error Handling Utilities for CEC

This module provides centralized error handling decorators and utilities to:
1. Reduce code duplication across modules
2. Provide consistent error messages
3. Add contextual information to exceptions
4. Simplify error handling logic

Author: CEC Team
Date: 2026-02-19
"""

import functools
import traceback
from typing import Any, Callable, Optional, TypeVar, Union
from .exceptions import (
    CECError,
    ParsingError,
    ProvingError,
    ValidationError
)

T = TypeVar('T')


def handle_proof_error(
    default_return: Any = None,
    reraise: bool = False,
    context: Optional[str] = None
) -> Callable:
    """
    Decorator to handle errors during proof operations.
    
    Catches exceptions during proof attempts and either returns a default value
    or re-raises with additional context.
    
    Args:
        default_return: Value to return if an error occurs (default: None)
        reraise: Whether to re-raise the exception with context (default: False)
        context: Additional context string to add to error messages
    
    Returns:
        Decorated function that handles proof errors gracefully
    
    Example:
        @handle_proof_error(default_return=ProofResult.FAILED)
        def attempt_proof(self, formula):
            # Proof logic that might fail
            ...
    
    Example with context:
        @handle_proof_error(reraise=True, context="Modal logic proof")
        def prove_modal(self, formula):
            # Modal proof logic
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Union[T, Any]]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Union[T, Any]:
            try:
                return func(*args, **kwargs)
            except ProvingError as e:
                # Already a proof error, just add context if needed
                if reraise:
                    if context:
                        e.args = (f"{context}: {e.args[0]}",) + e.args[1:]
                    raise
                return default_return
            except CECError as e:
                # Other DCEC exception during proof
                if reraise:
                    msg = f"{context}: {str(e)}" if context else str(e)
                    raise ProvingError(msg) from e
                return default_return
            except Exception as e:
                # Unexpected exception
                if reraise:
                    msg = f"Proof failed: {str(e)}"
                    if context:
                        msg = f"{context}: {msg}"
                    raise ProvingError(msg) from e
                return default_return
        return wrapper
    return decorator


def handle_parse_error(
    default_return: Any = None,
    reraise: bool = False,
    context: Optional[str] = None
) -> Callable:
    """
    Decorator to handle errors during parsing operations.
    
    Catches exceptions during formula parsing and either returns a default value
    or re-raises with additional context.
    
    Args:
        default_return: Value to return if an error occurs (default: None)
        reraise: Whether to re-raise the exception with context (default: False)
        context: Additional context string to add to error messages
    
    Returns:
        Decorated function that handles parse errors gracefully
    
    Example:
        @handle_parse_error(default_return=None)
        def parse_formula(self, text):
            # Parsing logic that might fail
            ...
    
    Example with reraise:
        @handle_parse_error(reraise=True, context="Temporal formula parsing")
        def parse_temporal(self, text):
            # Temporal parsing logic
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Union[T, Any]]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Union[T, Any]:
            try:
                return func(*args, **kwargs)
            except ParsingError as e:
                # Already a parse error, just add context if needed
                if reraise:
                    if context:
                        e.args = (f"{context}: {e.args[0]}",) + e.args[1:]
                    raise
                return default_return
            except CECError as e:
                # Other DCEC exception during parsing
                if reraise:
                    msg = f"{context}: {str(e)}" if context else str(e)
                    raise ParsingError(msg) from e
                return default_return
            except Exception as e:
                # Unexpected exception
                if reraise:
                    msg = f"Parse failed: {str(e)}"
                    if context:
                        msg = f"{context}: {msg}"
                    raise ParsingError(msg) from e
                return default_return
        return wrapper
    return decorator


def with_error_context(context: str) -> Callable:
    """
    Decorator to add contextual information to any exception raised.
    
    Wraps exceptions with additional context about where they occurred,
    making debugging easier.
    
    Args:
        context: Context string describing the operation
    
    Returns:
        Decorated function that adds context to exceptions
    
    Example:
        @with_error_context("Formula validation")
        def validate_formula(self, formula):
            # Validation logic
            if not formula.is_well_formed():
                raise ValidationError("Formula is not well-formed")
    
    The resulting error message will be:
        "Formula validation: Formula is not well-formed"
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except CECError as e:
                # Add context to DCEC exceptions
                e.args = (f"{context}: {e.args[0]}",) + e.args[1:]
                raise
            except Exception as e:
                # Wrap other exceptions with context
                raise CECError(f"{context}: {str(e)}") from e
        return wrapper
    return decorator


def safe_call(
    func: Callable[..., T],
    *args,
    default: Any = None,
    logger: Optional[Any] = None,
    **kwargs
) -> Union[T, Any]:
    """
    Safely call a function and return a default value on error.
    
    Useful for calling functions that might fail but where failure is acceptable.
    
    Args:
        func: Function to call
        *args: Positional arguments to pass to func
        default: Default value to return on error (default: None)
        logger: Optional logger to log errors
        **kwargs: Keyword arguments to pass to func
    
    Returns:
        Result of func or default value on error
    
    Example:
        result = safe_call(risky_operation, arg1, arg2, default=[], logger=log)
        if not result:
            # Handle failure case
            ...
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if logger:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            logger.debug(traceback.format_exc())
        return default


def format_error_message(
    error: Exception,
    operation: str,
    details: Optional[dict] = None
) -> str:
    """
    Format an error message with consistent structure.
    
    Creates user-friendly error messages with operation context and optional details.
    
    Args:
        error: The exception that occurred
        operation: Description of the operation that failed
        details: Optional dictionary of additional details
    
    Returns:
        Formatted error message string
    
    Example:
        try:
            prove_formula(f)
        except Exception as e:
            msg = format_error_message(
                e,
                "theorem proving",
                {"formula": str(f), "prover": "modal"}
            )
            raise ProvingError(msg)
    
    Result:
        "Error during theorem proving: <error message>
         Details: formula=..., prover=modal"
    """
    msg = f"Error during {operation}: {str(error)}"
    
    if details:
        details_str = ", ".join(f"{k}={v}" for k, v in details.items())
        msg += f"\nDetails: {details_str}"
    
    return msg


def validate_not_none(value: Any, name: str) -> None:
    """
    Validate that a value is not None.
    
    Args:
        value: Value to check
        name: Name of the value for error message
    
    Raises:
        ValidationError: If value is None
    
    Example:
        validate_not_none(formula, "formula")
        validate_not_none(prover, "prover")
    """
    if value is None:
        raise ValidationError(f"{name} cannot be None")


def validate_type(value: Any, expected_type: type, name: str) -> None:
    """
    Validate that a value has the expected type.
    
    Args:
        value: Value to check
        expected_type: Expected type
        name: Name of the value for error message
    
    Raises:
        ValidationError: If value is not of expected type
    
    Example:
        validate_type(formula, Formula, "formula")
        validate_type(agent, str, "agent")
    """
    if not isinstance(value, expected_type):
        raise ValidationError(
            f"{name} must be of type {expected_type.__name__}, "
            f"got {type(value).__name__}"
        )


# Convenience function for common validation pattern
def validate_formula(formula: Any, allow_none: bool = False) -> None:
    """
    Validate that a value is a proper Formula object.
    
    Args:
        formula: Value to validate
        allow_none: Whether to allow None as valid (default: False)
    
    Raises:
        ValidationError: If formula is None and not allowed
        ValidationError: If formula is not a Formula object
    
    Example:
        validate_formula(f)  # Must be non-None Formula
        validate_formula(f, allow_none=True)  # Can be None or Formula
    """
    if formula is None:
        if not allow_none:
            raise ValidationError("formula cannot be None")
        return
    
    # Import here to avoid circular imports
    from .dcec_core import Formula
    validate_type(formula, Formula, "formula")


__all__ = [
    'handle_proof_error',
    'handle_parse_error',
    'with_error_context',
    'safe_call',
    'format_error_message',
    'validate_not_none',
    'validate_type',
    'validate_formula',
]
