"""
Multi-Language Support MCP Tool — thin shim.

Business logic lives in:
    ipfs_datasets_py.processors.legal_scrapers.multilanguage_engine

This file re-exports the canonical standalone functions so the MCP tool
registry discovers them at the expected module path.
"""

from ipfs_datasets_py.processors.legal_scrapers.multilanguage_engine import (  # noqa: F401
    detect_query_language,
    translate_legal_query,
    cross_language_legal_search,
    get_legal_term_translations,
)

__all__ = [
    "detect_query_language",
    "translate_legal_query",
    "cross_language_legal_search",
    "get_legal_term_translations",
]
