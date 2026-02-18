"""Deontic logic utilities."""

from __future__ import annotations

from .converter import DeonticConverter
from .legal_text_to_deontic import convert_legal_text_to_deontic
from .analyzer import DeonticAnalyzer

__all__ = ["DeonticConverter", "convert_legal_text_to_deontic", "DeonticAnalyzer"]
