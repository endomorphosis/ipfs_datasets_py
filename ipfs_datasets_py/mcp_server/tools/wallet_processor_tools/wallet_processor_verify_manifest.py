"""MCP tool: verify a wallet export manifest."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.processors.wallets.api import VerifyManifestRequest

from ._helpers import error_response, mcp_api, success_response


@tool_metadata(
    category="wallet_processor_tools",
    mcp_description=(
        "Verify export manifest accounting (partition/finality/warning counts). "
        "Does not return wallet payloads."
    ),
    timeout_seconds=30.0,
)
async def wallet_processor_verify_manifest(
    path: Optional[str] = None,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Verify a manifest path or in-memory mapping."""
    try:
        api = mcp_api()
        result = api.verify_manifest(
            VerifyManifestRequest(path=path, manifest=manifest)
        )
        return success_response(result.to_dict())
    except Exception as exc:
        return error_response(exc)
