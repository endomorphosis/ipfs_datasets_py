"""MCP tool: list registered wallet processor families."""

from __future__ import annotations

from typing import Any, Dict

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import error_response, mcp_api, success_response


@tool_metadata(
    category="wallet_processor_tools",
    mcp_description=(
        "List registered wallet processor families without importing "
        "optional chain packages."
    ),
    timeout_seconds=15.0,
)
async def wallet_processor_list_families() -> Dict[str, Any]:
    """List families via the lazy registry (no chain SDK imports)."""
    try:
        api = mcp_api()
        return success_response(api.list_families().to_dict())
    except Exception as exc:
        return error_response(exc)
