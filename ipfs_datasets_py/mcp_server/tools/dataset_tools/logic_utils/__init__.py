# ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/__init__.py
"""
Logic utilities for text to formal logic conversion.

This module provides shared utilities for converting natural language
into formal logic representations (FOL, deontic logic, etc.).
"""

from .predicate_extractor import extract_predicates, normalize_predicate
from .logic_formatter import format_fol, format_deontic, format_output
from .fol_parser import parse_quantifiers, build_fol_formula, validate_fol_syntax
from .deontic_parser import extract_normative_elements, build_deontic_formula, identify_obligations

__all__ = [
    "extract_predicates",
    "normalize_predicate", 
    "format_fol",
    "format_deontic",
    "format_output",
    "parse_quantifiers",
    "build_fol_formula",
    "validate_fol_syntax",
    "extract_normative_elements",
    "build_deontic_formula",
    "identify_obligations"
]
