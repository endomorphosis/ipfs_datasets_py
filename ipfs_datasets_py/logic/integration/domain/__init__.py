"""Domain-specific integrations for the logic module.

Package exports are resolved lazily so importing one lightweight domain module
does not initialize unrelated prover bridges or optional SymbolicAI runtimes.

Components:
- Legal: Domain knowledge, symbolic analysis, bulk processing
- Medical: Theorem proving framework
- Contracts: Symbolic contract verification
- Deontic: Query engines and temporal APIs
- Document: Consistency checking
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_EXPORTS = {
    "LegalDomainKnowledge": (".legal_domain_knowledge", "LegalDomainKnowledge"),
    "LegalSymbolicAnalyzer": (".legal_symbolic_analyzer", "LegalSymbolicAnalyzer"),
    "DeonticQueryEngine": (".deontic_query_engine", "DeonticQueryEngine"),
    "TemporalDeonticAPI": (".temporal_deontic_api", "TemporalDeonticAPI"),
    "DocumentConsistencyChecker": (
        ".document_consistency_checker",
        "DocumentConsistencyChecker",
    ),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = target
    try:
        value = getattr(importlib.import_module(module_name, __name__), attribute_name)
    except ImportError:
        value = None
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))

__all__ = [
    "LegalDomainKnowledge",
    "LegalSymbolicAnalyzer",
    "DeonticQueryEngine",
    "TemporalDeonticAPI",
    "DocumentConsistencyChecker",
]
