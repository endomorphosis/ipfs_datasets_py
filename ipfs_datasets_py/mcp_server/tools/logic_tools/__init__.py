"""Logic MCP tool wrappers."""

from .temporal_deontic_logic_tools import (
    TEMPORAL_DEONTIC_LOGIC_TOOLS,
    add_theorem,
    bulk_process_caselaw,
    check_document_consistency,
    query_theorems,
)

__all__ = [
    "TEMPORAL_DEONTIC_LOGIC_TOOLS",
    "check_document_consistency",
    "query_theorems",
    "bulk_process_caselaw",
    "add_theorem",
]
