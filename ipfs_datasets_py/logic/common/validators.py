"""
Input Validation Utilities for Logic Module.

Provides reusable validation helpers for all public-facing functions
across the logic module:

- Formula string validation (size limits, character safety)
- List input validation (axiom lists, formula sets)
- Logic system validation (supported systems check)
- Timeout validation (bounds checking)

Usage:
    from ipfs_datasets_py.logic.common.validators import (
        validate_formula_string,
        validate_axiom_list,
        validate_logic_system,
        validate_timeout_ms,
    )

    def my_function(formula: str, logic: str = "tdfol"):
        validate_formula_string(formula)
        validate_logic_system(logic)
        ...
"""

from __future__ import annotations

import re
from typing import List, Optional, Set

from .errors import ValidationError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_FORMULA_LENGTH = 100_000
"""Maximum characters allowed in a formula string."""

MAX_AXIOM_COUNT = 500
"""Maximum number of axioms in a single formula set."""

MAX_AXIOM_LENGTH = 50_000
"""Maximum characters allowed in a single axiom."""

MAX_TIMEOUT_MS = 60_000
"""Maximum allowed timeout in milliseconds (60 seconds)."""

MIN_TIMEOUT_MS = 10
"""Minimum allowed timeout in milliseconds."""

SUPPORTED_LOGICS: Set[str] = {"tdfol", "cec", "fol", "deontic", "modal", "temporal"}
"""Set of supported logic system identifiers."""

SUPPORTED_FORMATS: Set[str] = {"auto", "tdfol", "dcec", "fol", "tptp", "nl"}
"""Set of supported formula format identifiers."""

# Suspicious pattern — catch obvious injection attempts
_INJECTION_PATTERN = re.compile(
    r"(?:"
    r"__import__"
    r"|eval\s*\("
    r"|exec\s*\("
    r"|subprocess"
    r"|os\.system"
    r"|open\s*\("
    r")",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_formula_string(
    formula: str,
    *,
    field_name: str = "formula",
    max_length: int = MAX_FORMULA_LENGTH,
    allow_empty: bool = False,
) -> None:
    """
    Validate a formula string.

    Checks:
    - Type is str
    - Not empty (unless allow_empty=True)
    - Does not exceed max_length
    - Does not contain suspicious injection patterns

    Args:
        formula: The formula string to validate.
        field_name: Human-readable field name for error messages.
        max_length: Maximum allowed length in characters.
        allow_empty: Whether an empty string is acceptable.

    Raises:
        ValidationError: If validation fails.

    Example:
        >>> validate_formula_string("P ∧ Q → R")  # OK
        >>> validate_formula_string("")  # Raises ValidationError
    """
    if not isinstance(formula, str):
        raise ValidationError(
            f"'{field_name}' must be a string, got {type(formula).__name__}",
            context={"field": field_name, "type": type(formula).__name__},
        )
    if not allow_empty and not formula.strip():
        raise ValidationError(
            f"'{field_name}' must not be empty.",
            context={"field": field_name},
        )
    if len(formula) > max_length:
        raise ValidationError(
            f"'{field_name}' exceeds maximum length of {max_length} characters "
            f"(got {len(formula)}).",
            context={"field": field_name, "length": len(formula), "max": max_length},
        )
    if _INJECTION_PATTERN.search(formula):
        raise ValidationError(
            f"'{field_name}' contains potentially unsafe content.",
            context={"field": field_name},
        )


def validate_axiom_list(
    axioms: List[str],
    *,
    max_count: int = MAX_AXIOM_COUNT,
    max_axiom_length: int = MAX_AXIOM_LENGTH,
) -> None:
    """
    Validate a list of axiom strings.

    Checks:
    - Type is list
    - Does not exceed max_count items
    - Each axiom is a valid string (non-empty, within max_axiom_length)

    Args:
        axioms: List of axiom strings to validate.
        max_count: Maximum number of axioms allowed.
        max_axiom_length: Maximum characters per axiom.

    Raises:
        ValidationError: If validation fails.

    Example:
        >>> validate_axiom_list(["P → Q", "P"])  # OK
        >>> validate_axiom_list(["a"] * 1000)    # Raises ValidationError
    """
    if not isinstance(axioms, list):
        raise ValidationError(
            f"'axioms' must be a list, got {type(axioms).__name__}",
            context={"type": type(axioms).__name__},
        )
    if len(axioms) > max_count:
        raise ValidationError(
            f"'axioms' list exceeds maximum of {max_count} items (got {len(axioms)}).",
            context={"count": len(axioms), "max": max_count},
        )
    for idx, axiom in enumerate(axioms):
        try:
            validate_formula_string(
                axiom,
                field_name=f"axioms[{idx}]",
                max_length=max_axiom_length,
            )
        except ValidationError as exc:
            raise ValidationError(
                str(exc),
                context={**exc.context, "axiom_index": idx},
            ) from exc


def validate_logic_system(
    logic: str,
    *,
    supported: Optional[Set[str]] = None,
) -> None:
    """
    Validate a logic system identifier.

    Args:
        logic: The logic system string (e.g., "tdfol", "cec").
        supported: Set of supported logic identifiers. Defaults to SUPPORTED_LOGICS.

    Raises:
        ValidationError: If the logic system is not supported.

    Example:
        >>> validate_logic_system("tdfol")      # OK
        >>> validate_logic_system("invalid")    # Raises ValidationError
    """
    if supported is None:
        supported = SUPPORTED_LOGICS
    if not isinstance(logic, str):
        raise ValidationError(
            f"'logic' must be a string, got {type(logic).__name__}",
            context={"type": type(logic).__name__},
        )
    if logic.lower() not in supported:
        raise ValidationError(
            f"Unsupported logic system: '{logic}'. "
            f"Supported: {sorted(supported)}",
            context={"logic": logic, "supported": sorted(supported)},
        )


def validate_timeout_ms(
    timeout_ms: int,
    *,
    min_ms: int = MIN_TIMEOUT_MS,
    max_ms: int = MAX_TIMEOUT_MS,
) -> None:
    """
    Validate a timeout value in milliseconds.

    Args:
        timeout_ms: Timeout in milliseconds.
        min_ms: Minimum allowed value (default: 10ms).
        max_ms: Maximum allowed value (default: 60000ms).

    Raises:
        ValidationError: If the timeout is out of bounds.

    Example:
        >>> validate_timeout_ms(5000)     # OK
        >>> validate_timeout_ms(1)        # Raises ValidationError
        >>> validate_timeout_ms(999999)   # Raises ValidationError
    """
    if not isinstance(timeout_ms, int):
        raise ValidationError(
            f"'timeout_ms' must be an integer, got {type(timeout_ms).__name__}",
            context={"type": type(timeout_ms).__name__},
        )
    if timeout_ms < min_ms:
        raise ValidationError(
            f"'timeout_ms' must be ≥ {min_ms}ms (got {timeout_ms}ms).",
            context={"value": timeout_ms, "min": min_ms},
        )
    if timeout_ms > max_ms:
        raise ValidationError(
            f"'timeout_ms' must be ≤ {max_ms}ms (got {timeout_ms}ms).",
            context={"value": timeout_ms, "max": max_ms},
        )


def validate_format(
    fmt: str,
    *,
    supported: Optional[Set[str]] = None,
) -> None:
    """
    Validate a formula format identifier.

    Args:
        fmt: Format string (e.g., "tdfol", "dcec", "auto").
        supported: Set of supported formats. Defaults to SUPPORTED_FORMATS.

    Raises:
        ValidationError: If the format is not supported.

    Example:
        >>> validate_format("tdfol")    # OK
        >>> validate_format("xml")     # Raises ValidationError
    """
    if supported is None:
        supported = SUPPORTED_FORMATS
    if fmt not in supported:
        raise ValidationError(
            f"Unsupported format: '{fmt}'. Supported: {sorted(supported)}",
            context={"format": fmt, "supported": sorted(supported)},
        )
