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
    classify_legal_entity,
    detect_normative_conflicts,
    extract_action_recipient,
    extract_conditions,
    extract_cross_references,
    extract_definition_body,
    extract_enumerated_items,
    extract_exceptions,
    extract_legal_action,
    extract_legal_subject,
    extract_normative_elements,
    extract_override_clauses,
    extract_temporal_constraints,
    identify_obligations,
    normalize_predicate_name,
    score_scaffold_quality,
)

__all__ = [
    "analyze_normative_sentence",
    "build_deontic_formula",
    "classify_modal",
    "classify_legal_entity",
    "detect_normative_conflicts",
    "extract_action_recipient",
    "extract_conditions",
    "extract_cross_references",
    "extract_definition_body",
    "extract_enumerated_items",
    "extract_exceptions",
    "extract_legal_action",
    "extract_legal_subject",
    "extract_normative_elements",
    "extract_override_clauses",
    "extract_temporal_constraints",
    "identify_obligations",
    "normalize_predicate_name",
    "score_scaffold_quality",
]
