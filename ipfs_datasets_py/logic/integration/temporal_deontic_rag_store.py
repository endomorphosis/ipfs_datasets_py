"""Compatibility import for the temporal deontic RAG store.

The implementation lives under ``logic.integration.domain``.  This module keeps
older imports working while tests and callers migrate to the domain package.
"""

from .domain.temporal_deontic_rag_store import (
    ConsistencyResult,
    TemporalDeonticRAGStore,
    TheoremMetadata,
)

__all__ = [
    "ConsistencyResult",
    "TemporalDeonticRAGStore",
    "TheoremMetadata",
]
