"""
Legacy MCP Tools — Deprecated

This package contains the original monolithic MCP tool implementations that
predate the per-category directory structure. All 32 files in this package
have been superseded by tools in the dedicated category directories.

.. deprecated::
    Import from the corresponding category directory instead.
    See MIGRATION_GUIDE.md for the complete migration map.
"""
# ipfs_datasets_py/mcp_tools/tools/__init__.py

# Import temporal deontic logic tools via canonical, non-deprecated logic-tools path
from ..logic_tools.temporal_deontic_logic_tools import (
    add_theorem,
    bulk_process_caselaw,
    check_document_consistency,
    query_theorems,
)

TEMPORAL_DEONTIC_LOGIC_TOOLS = [
    check_document_consistency,
    query_theorems,
    bulk_process_caselaw,
    add_theorem,
]

__all__ = ['TEMPORAL_DEONTIC_LOGIC_TOOLS']
