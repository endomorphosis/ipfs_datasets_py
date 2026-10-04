"""MCP tool: declared wallet processor capabilities (no chain extras)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.processors.wallets.api import CapabilitiesRequest

from ._helpers import error_response, mcp_api, success_response


@tool_metadata(
    category="wallet_processor_tools",
    mcp_description=(
        "List or select declared wallet processor capabilities without "
        "loading chain extras. Signing/broadcast are always false."
    ),
    timeout_seconds=15.0,
)
async def wallet_processor_capabilities(
    family: Optional[str] = None,
    network: Optional[str] = None,
) -> Dict[str, Any]:
    """Return declared capabilities for families or a selected family/network."""
    try:
        api = mcp_api()
        result = api.capabilities(
            CapabilitiesRequest(family=family, network=network)
        )
        return success_response(result.to_dict())
    except Exception as exc:
        return error_response(exc)
