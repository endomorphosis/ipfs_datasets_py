"""Input validation helpers for the logic module.

Provides a lightweight API expected by ``ipfs_datasets_py.logic.security``
imports. This module wraps the common validators in
``ipfs_datasets_py.logic.common.validators`` to avoid duplication while keeping
API compatibility with the security package.
"""

from __future__ import annotations

from typing import Iterable, List

from ..common.errors import ValidationError
from ..common.validators import validate_formula_string


MAX_TEXT_LENGTH = 10000


def validate_text(text: str, *, max_length: int = MAX_TEXT_LENGTH) -> None:
    """Validate free-form text inputs.

    Args:
        text: Input text to validate.
        max_length: Maximum allowed length.

    Raises:
        ValidationError: When validation fails.
    """
    if not isinstance(text, str):
        raise ValidationError(
            f"'text' must be a string, got {type(text).__name__}",
            context={"field": "text", "type": type(text).__name__},
        )
    if not text.strip():
        raise ValidationError("'text' must not be empty.", context={"field": "text"})
    if len(text) > max_length:
        raise ValidationError(
            f"'text' exceeds maximum length of {max_length} characters (got {len(text)}).",
            context={"field": "text", "length": len(text), "max": max_length},
        )


def validate_formula(formula: str) -> None:
    """Validate a single logic formula string.

    Args:
        formula: Formula string to validate.

    Raises:
        ValidationError: When validation fails.
    """
    validate_formula_string(formula, field_name="formula")


def validate_formula_list(formulas: Iterable[str]) -> None:
    """Validate an iterable of formula strings.

    Args:
        formulas: Iterable of formula strings.

    Raises:
        ValidationError: When any formula fails validation.
    """
    if not isinstance(formulas, Iterable):
        raise ValidationError(
            f"'formulas' must be iterable, got {type(formulas).__name__}",
            context={"field": "formulas", "type": type(formulas).__name__},
        )
    for idx, formula in enumerate(list(formulas)):
        validate_formula_string(formula, field_name=f"formulas[{idx}]")


class InputValidator:
    """Simple validator wrapper for logic inputs."""

    def validate_text(self, text: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
        validate_text(text, max_length=max_length)
        return text

    def validate_formula(self, formula: str) -> str:
        validate_formula(formula)
        return formula

    def validate_formula_list(self, formulas: Iterable[str]) -> List[str]:
        validate_formula_list(formulas)
        return list(formulas)


__all__ = [
    "InputValidator",
    "ValidationError",
    "validate_text",
    "validate_formula",
    "validate_formula_list",
]
