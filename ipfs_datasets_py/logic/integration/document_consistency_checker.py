"""Compatibility import for the temporal deontic document checker.

The implementation lives under ``logic.integration.domain``.  This module keeps
older imports working while tests and callers migrate to the domain package.
"""

from .domain.document_consistency_checker import (
    DebugReport,
    DocumentAnalysis,
    DocumentConsistencyChecker,
)

__all__ = [
    "DebugReport",
    "DocumentAnalysis",
    "DocumentConsistencyChecker",
]
