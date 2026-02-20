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

# Import temporal deontic logic tools
from .temporal_deontic_logic_tools import TEMPORAL_DEONTIC_LOGIC_TOOLS

__all__ = ['TEMPORAL_DEONTIC_LOGIC_TOOLS']
