"""Deontic logic utilities."""

from __future__ import annotations

from .converter import DeonticConverter
from .formula_builder import build_deontic_formula_from_ir, parser_element_to_formula
from .ir import LegalNormIR, LegalNormQuality, SourceSpan, parser_element_to_ir
from .exports import (
    build_document_export_tables_from_ir,
    build_formal_logic_record_from_ir,
    build_proof_obligation_record_from_ir,
    parser_elements_to_export_tables,
    validate_export_tables,
)
from .metrics import summarize_parser_elements
from .legal_text_to_deontic import convert_legal_text_to_deontic
from .analyzer import DeonticAnalyzer
from .graph import (
    DeonticConflict,
    DeonticGraph,
    DeonticGraphBuilder,
    DeonticModality,
    DeonticNode,
    DeonticNodeType,
    DeonticRuleAssessment,
    DeonticRule,
)
from .support_map import (
    FilingSupportReference,
    MotionSupportMap,
    SupportFact,
    SupportMapBuilder,
    SupportMapEntry,
)
from .knowledge_base import (
    Action,
    Conjunction,
    DeonticKnowledgeBase,
    DeonticStatement,
    Disjunction,
    Implication,
    KnowledgeDeonticModality,
    KnowledgeLogicalOperator,
    KnowledgeTemporalOperator,
    Negation,
    Party,
    Predicate,
    Proposition,
    TimeInterval,
)

__all__ = [
    "DeonticAnalyzer",
    "DeonticConflict",
    "DeonticConverter",
    "LegalNormIR",
    "LegalNormQuality",
    "SourceSpan",
    "build_deontic_formula_from_ir",
    "build_document_export_tables_from_ir",
    "build_formal_logic_record_from_ir",
    "build_proof_obligation_record_from_ir",
    "parser_elements_to_export_tables",
    "validate_export_tables",
    "DeonticKnowledgeBase",
    "DeonticGraph",
    "DeonticGraphBuilder",
    "DeonticModality",
    "DeonticNode",
    "DeonticNodeType",
    "DeonticStatement",
    "DeonticRuleAssessment",
    "DeonticRule",
    "Action",
    "Conjunction",
    "Disjunction",
    "FilingSupportReference",
    "Implication",
    "KnowledgeDeonticModality",
    "KnowledgeLogicalOperator",
    "KnowledgeTemporalOperator",
    "MotionSupportMap",
    "Negation",
    "Party",
    "Predicate",
    "Proposition",
    "SupportFact",
    "SupportMapBuilder",
    "SupportMapEntry",
    "TimeInterval",
    "convert_legal_text_to_deontic",
    "parser_element_to_ir",
    "parser_element_to_formula",
    "summarize_parser_elements",
]
