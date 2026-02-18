"""
Natural Language Processing for TDFOL

This module provides pattern-based natural language to TDFOL conversion.
Requires spaCy (install with: pip install ipfs_datasets_py[knowledge_graphs])
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tdfol_nl_preprocessor import NLPreprocessor, ProcessedDocument, Entity
    from .tdfol_nl_patterns import PatternMatcher, PatternMatch, Pattern, PatternType
    from .tdfol_nl_generator import FormulaGenerator, GeneratedFormula
    from .tdfol_nl_context import ContextResolver, Context
    from .tdfol_nl_api import (
        NLParser,
        ParseOptions,
        ParseResult,
        parse_natural_language,
        parse_natural_language_batch,
    )

__all__ = [
    # Preprocessor
    "NLPreprocessor",
    "ProcessedDocument",
    "Entity",
    
    # Pattern Matching
    "PatternMatcher",
    "PatternMatch",
    "Pattern",
    "PatternType",
    
    # Formula Generation
    "FormulaGenerator",
    "GeneratedFormula",
    
    # Context Resolution
    "ContextResolver",
    "Context",
    
    # Unified API
    "NLParser",
    "ParseOptions",
    "ParseResult",
    "parse_natural_language",
    "parse_natural_language_batch",
]

__version__ = "0.1.0"


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Preprocessor
    "NLPreprocessor": (".tdfol_nl_preprocessor", "NLPreprocessor"),
    "ProcessedDocument": (".tdfol_nl_preprocessor", "ProcessedDocument"),
    "Entity": (".tdfol_nl_preprocessor", "Entity"),
    
    # Pattern Matching
    "PatternMatcher": (".tdfol_nl_patterns", "PatternMatcher"),
    "PatternMatch": (".tdfol_nl_patterns", "PatternMatch"),
    "Pattern": (".tdfol_nl_patterns", "Pattern"),
    "PatternType": (".tdfol_nl_patterns", "PatternType"),
    
    # Formula Generation
    "FormulaGenerator": (".tdfol_nl_generator", "FormulaGenerator"),
    "GeneratedFormula": (".tdfol_nl_generator", "GeneratedFormula"),
    
    # Context Resolution
    "ContextResolver": (".tdfol_nl_context", "ContextResolver"),
    "Context": (".tdfol_nl_context", "Context"),
    
    # Unified API
    "NLParser": (".tdfol_nl_api", "NLParser"),
    "ParseOptions": (".tdfol_nl_api", "ParseOptions"),
    "ParseResult": (".tdfol_nl_api", "ParseResult"),
    "parse_natural_language": (".tdfol_nl_api", "parse_natural_language"),
    "parse_natural_language_batch": (".tdfol_nl_api", "parse_natural_language_batch"),
}


def __getattr__(name: str):
    """Lazy loading for NL module components."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
