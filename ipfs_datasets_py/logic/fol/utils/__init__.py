"""Pure logic parsing helpers used by core conversion APIs."""

from .predicate_extractor import extract_predicates, extract_logical_relations, extract_variables
from .fol_parser import (
    parse_quantifiers,
    parse_logical_operators,
    build_fol_formula,
    validate_fol_syntax,
    convert_to_prolog,
    convert_to_tptp,
)
from .deontic_parser import (
    extract_normative_elements,
    analyze_normative_sentence,
    build_deontic_formula,
    identify_obligations,
    detect_normative_conflicts,
)
from .logic_formatter import format_fol, format_deontic, format_output

__all__ = [
    "extract_predicates",
    "extract_logical_relations",
    "extract_variables",
    "parse_quantifiers",
    "parse_logical_operators",
    "build_fol_formula",
    "validate_fol_syntax",
    "convert_to_prolog",
    "convert_to_tptp",
    "extract_normative_elements",
    "analyze_normative_sentence",
    "build_deontic_formula",
    "identify_obligations",
    "detect_normative_conflicts",
    "format_fol",
    "format_deontic",
    "format_output",
]
