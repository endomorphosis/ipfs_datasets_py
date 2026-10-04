"""First-Order Logic (FOL) utilities."""

from __future__ import annotations

from .converter import FOLConverter
from .text_to_fol import convert_text_to_fol

__all__ = [
    "FOLConverter",  # Recommended: New unified converter
    "convert_text_to_fol",  # Legacy: Deprecated, use FOLConverter instead
]
