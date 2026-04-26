# ipfs_datasets_py/mcp_server/tools/dataset_tools/logic_utils/deontic_parser.py
"""Compatibility wrapper for deterministic deontic parsing utilities.

The MCP dataset-tools path used to carry a stale copy of the parser.  Re-export
the core implementation so CLI/MCP tools and library code share the same legal
modal precedence, exception handling, and low-confidence scaffold behavior.
"""

from ipfs_datasets_py.logic.deontic.utils.deontic_parser import (  # noqa: F401
    analyze_normative_sentence,
    build_deontic_formula,
    classify_modal,
    detect_normative_conflicts,
    extract_conditions,
    extract_exceptions,
    extract_legal_action,
    extract_legal_subject,
    extract_normative_elements,
    extract_temporal_constraints,
    identify_obligations,
    normalize_predicate_name,
)

__all__ = [
    "analyze_normative_sentence",
    "build_deontic_formula",
    "classify_modal",
    "detect_normative_conflicts",
    "extract_conditions",
    "extract_exceptions",
    "extract_legal_action",
    "extract_legal_subject",
    "extract_normative_elements",
    "extract_temporal_constraints",
    "identify_obligations",
    "normalize_predicate_name",
]
