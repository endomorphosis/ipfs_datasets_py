"""
Temporal Deontic First-Order Logic (TDFOL) Module

This module provides a unified framework for reasoning about temporal, deontic,
and first-order logic. It combines:
- First-Order Logic (FOL): predicates, quantifiers, variables, functions
- Deontic Logic: obligations (O), permissions (P), prohibitions (F)
- Temporal Logic: temporal operators (□, ◊, X, U, S)

The TDFOL system enables neurosymbolic reasoning combining:
- Symbolic theorem proving
- Neural pattern matching
- Knowledge graph integration
- Vector-based retrieval
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .tdfol_core import (
    # Enumerations
    DeonticOperator,
    LogicOperator,
    Quantifier,
    Sort,
    TemporalOperator,
    
    # Terms
    Constant,
    FunctionApplication,
    Term,
    Variable,
    
    # Formulas
    BinaryFormula,
    BinaryTemporalFormula,
    DeonticFormula,
    Formula,
    Predicate,
    QuantifiedFormula,
    TemporalFormula,
    UnaryFormula,
    
    # Knowledge Base
    TDFOLKnowledgeBase,
    
    # Proof Results (Phase 1 Task 1.2 - Unified)
    ProofStatus,
    ProofStep,
    ProofResult,
    
    # Expansion Rules (Phase 1 Task 1.1)
    ExpansionContext,
    ExpansionResult,
    ExpansionRule,
    
    # Utility Functions
    create_always,
    create_conjunction,
    create_disjunction,
    create_eventually,
    create_existential,
    create_implication,
    create_negation,
    create_next,
    create_obligation,
    create_permission,
    create_prohibition,
    create_universal,
    create_until,
)

# Keep package imports quiet/deterministic: do not import optional/heavy submodules
# (parsers, DCEC integration, prover, cache, rule loaders) at import time.

if TYPE_CHECKING:
    from .tdfol_parser import TDFOLLexer, TDFOLParser, parse_tdfol, parse_tdfol_safe
    from .tdfol_dcec_parser import DCECStringParser, parse_dcec, parse_dcec_safe
    from .tdfol_prover import ProofResult, ProofStatus, ProofStep, TDFOLProver
    from .tdfol_proof_cache import (
        TDFOLProofCache,
        get_global_proof_cache,
        clear_global_proof_cache,
        TDFOLProofResult,
    )
    from .tdfol_inference_rules import TDFOLInferenceRule, get_all_tdfol_rules
    from .nl.tdfol_nl_preprocessor import NLPreprocessor, ProcessedDocument, Entity
    from .proof_tree_visualizer import (
        ProofTreeVisualizer,
        ProofTreeNode,
        NodeType,
        TreeStyle,
        VerbosityLevel,
        visualize_proof,
    )
    from .formula_dependency_graph import (
        FormulaDependencyGraph,
        DependencyNode,
        DependencyEdge,
        FormulaType,
        DependencyType,
        CircularDependencyError,
        analyze_proof_dependencies,
        find_proof_chain,
    )
    from .countermodel_visualizer import (
        CountermodelVisualizer,
        BoxChars,
        GraphLayout,
        create_visualizer,
    )
    from .performance_dashboard import (
        PerformanceDashboard,
        ProofMetrics,
        TimeSeriesMetric,
        AggregatedStats,
        MetricType,
        get_global_dashboard,
        reset_global_dashboard,
    )
    from .security_validator import (
        SecurityValidator,
        SecurityConfig,
        SecurityLevel,
        ThreatType,
        ValidationResult,
        AuditResult,
        RateLimiter,
        create_validator,
        validate_formula,
        audit_proof,
    )
    from .performance_metrics import (
        MetricsCollector,
        TimingResult,
        MemoryResult,
        StatisticalSummary,
        get_global_collector,
        reset_global_collector,
    )

__all__ = [
    # Enumerations
    "DeonticOperator",
    "LogicOperator",
    "Quantifier",
    "Sort",
    "TemporalOperator",
    
    # Terms
    "Constant",
    "FunctionApplication",
    "Term",
    "Variable",
    
    # Formulas
    "BinaryFormula",
    "BinaryTemporalFormula",
    "DeonticFormula",
    "Formula",
    "Predicate",
    "QuantifiedFormula",
    "TemporalFormula",
    "UnaryFormula",
    
    # Knowledge Base
    "TDFOLKnowledgeBase",
    
    # Proof Results (Phase 1 Task 1.2 - Unified)
    "ProofStatus",
    "ProofStep",
    "ProofResult",
    
    # Expansion Rules (Phase 1 Task 1.1)
    "ExpansionContext",
    "ExpansionResult",
    "ExpansionRule",
    
    # Parser
    "TDFOLLexer",
    "TDFOLParser",
    "parse_tdfol",
    "parse_tdfol_safe",
    
    # DCEC Parser
    "DCECStringParser",
    "parse_dcec",
    "parse_dcec_safe",
    
    # Prover
    "ProofResult",
    "ProofStatus",
    "ProofStep",
    "TDFOLProver",
    
    # Proof Cache
    "TDFOLProofCache",
    "get_global_proof_cache",
    "clear_global_proof_cache",
    "TDFOLProofResult",
    
    # Inference Rules
    "TDFOLInferenceRule",
    "get_all_tdfol_rules",
    
    # Natural Language Processing (Phase 7)
    "NLPreprocessor",
    "ProcessedDocument",
    "Entity",
    
    # Proof Tree Visualizer (Phase 11)
    "ProofTreeVisualizer",
    "ProofTreeNode",
    "NodeType",
    "TreeStyle",
    "VerbosityLevel",
    "visualize_proof",
    
    # Formula Dependency Graph (Phase 11)
    "FormulaDependencyGraph",
    "DependencyNode",
    "DependencyEdge",
    "FormulaType",
    "DependencyType",
    "CircularDependencyError",
    "analyze_proof_dependencies",
    "find_proof_chain",
    
    # Countermodel Visualizer (Phase 11)
    "CountermodelVisualizer",
    "BoxChars",
    "GraphLayout",
    "create_visualizer",
    
    # Performance Dashboard (Phase 11 Task 11.4)
    "PerformanceDashboard",
    "ProofMetrics",
    "TimeSeriesMetric",
    "AggregatedStats",
    "MetricType",
    "get_global_dashboard",
    "reset_global_dashboard",
    
    # Security Validator (Phase 12 Task 12.2)
    "SecurityValidator",
    "SecurityConfig",
    "SecurityLevel",
    "ThreatType",
    
    # Performance Metrics (Phase 1 Task 1.4)
    "MetricsCollector",
    "TimingResult",
    "MemoryResult",
    "StatisticalSummary",
    "get_global_collector",
    "reset_global_collector",
    "ValidationResult",
    "AuditResult",
    "RateLimiter",
    "create_validator",
    "validate_formula",
    "audit_proof",
    
    # Utility Functions
    "create_always",
    "create_conjunction",
    "create_disjunction",
    "create_eventually",
    "create_existential",
    "create_implication",
    "create_negation",
    "create_next",
    "create_obligation",
    "create_permission",
    "create_prohibition",
    "create_universal",
    "create_until",
]

__version__ = "1.0.0"


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Parser
    "TDFOLLexer": (".tdfol_parser", "TDFOLLexer"),
    "TDFOLParser": (".tdfol_parser", "TDFOLParser"),
    "parse_tdfol": (".tdfol_parser", "parse_tdfol"),
    "parse_tdfol_safe": (".tdfol_parser", "parse_tdfol_safe"),
    # DCEC Parser
    "DCECStringParser": (".tdfol_dcec_parser", "DCECStringParser"),
    "parse_dcec": (".tdfol_dcec_parser", "parse_dcec"),
    "parse_dcec_safe": (".tdfol_dcec_parser", "parse_dcec_safe"),
    # Prover
    "ProofResult": (".tdfol_prover", "ProofResult"),
    "ProofStatus": (".tdfol_prover", "ProofStatus"),
    "ProofStep": (".tdfol_prover", "ProofStep"),
    "TDFOLProver": (".tdfol_prover", "TDFOLProver"),
    # Proof Cache
    "TDFOLProofCache": (".tdfol_proof_cache", "TDFOLProofCache"),
    "get_global_proof_cache": (".tdfol_proof_cache", "get_global_proof_cache"),
    "clear_global_proof_cache": (".tdfol_proof_cache", "clear_global_proof_cache"),
    "TDFOLProofResult": (".tdfol_proof_cache", "TDFOLProofResult"),
    # Inference Rules
    "TDFOLInferenceRule": (".tdfol_inference_rules", "TDFOLInferenceRule"),
    "get_all_tdfol_rules": (".tdfol_inference_rules", "get_all_tdfol_rules"),
    # Natural Language Processing
    "NLPreprocessor": (".nl.tdfol_nl_preprocessor", "NLPreprocessor"),
    "ProcessedDocument": (".nl.tdfol_nl_preprocessor", "ProcessedDocument"),
    "Entity": (".nl.tdfol_nl_preprocessor", "Entity"),
    # Proof Tree Visualizer
    "ProofTreeVisualizer": (".proof_tree_visualizer", "ProofTreeVisualizer"),
    "ProofTreeNode": (".proof_tree_visualizer", "ProofTreeNode"),
    "NodeType": (".proof_tree_visualizer", "NodeType"),
    "TreeStyle": (".proof_tree_visualizer", "TreeStyle"),
    "VerbosityLevel": (".proof_tree_visualizer", "VerbosityLevel"),
    "visualize_proof": (".proof_tree_visualizer", "visualize_proof"),
    # Formula Dependency Graph
    "FormulaDependencyGraph": (".formula_dependency_graph", "FormulaDependencyGraph"),
    "DependencyNode": (".formula_dependency_graph", "DependencyNode"),
    "DependencyEdge": (".formula_dependency_graph", "DependencyEdge"),
    "FormulaType": (".formula_dependency_graph", "FormulaType"),
    "DependencyType": (".formula_dependency_graph", "DependencyType"),
    "CircularDependencyError": (".formula_dependency_graph", "CircularDependencyError"),
    "analyze_proof_dependencies": (".formula_dependency_graph", "analyze_proof_dependencies"),
    "find_proof_chain": (".formula_dependency_graph", "find_proof_chain"),
    # Countermodel Visualizer
    "CountermodelVisualizer": (".countermodel_visualizer", "CountermodelVisualizer"),
    "BoxChars": (".countermodel_visualizer", "BoxChars"),
    "GraphLayout": (".countermodel_visualizer", "GraphLayout"),
    "create_visualizer": (".countermodel_visualizer", "create_visualizer"),
    # Performance Dashboard
    "PerformanceDashboard": (".performance_dashboard", "PerformanceDashboard"),
    "ProofMetrics": (".performance_dashboard", "ProofMetrics"),
    "TimeSeriesMetric": (".performance_dashboard", "TimeSeriesMetric"),
    "AggregatedStats": (".performance_dashboard", "AggregatedStats"),
    "MetricType": (".performance_dashboard", "MetricType"),
    "get_global_dashboard": (".performance_dashboard", "get_global_dashboard"),
    "reset_global_dashboard": (".performance_dashboard", "reset_global_dashboard"),
    # Security Validator
    "SecurityValidator": (".security_validator", "SecurityValidator"),
    "SecurityConfig": (".security_validator", "SecurityConfig"),
    "SecurityLevel": (".security_validator", "SecurityLevel"),
    "ThreatType": (".security_validator", "ThreatType"),
    "ValidationResult": (".security_validator", "ValidationResult"),
    "AuditResult": (".security_validator", "AuditResult"),
    "RateLimiter": (".security_validator", "RateLimiter"),
    "create_validator": (".security_validator", "create_validator"),
    "validate_formula": (".security_validator", "validate_formula"),
    "audit_proof": (".security_validator", "audit_proof"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value