"""MCP tool: sanitized wallet processor job status."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.processors.wallets.api import StatusRequest

from ._helpers import error_response, mcp_api, success_response


@tool_metadata(
    category="wallet_processor_tools",
    mcp_description=(
        "Return a sanitized job status receipt. Never includes wallet "
        "payloads, secrets, or full provider endpoints."
    ),
    timeout_seconds=30.0,
)
async def wallet_processor_status(
    job_id: str,
    allowed_provider_hosts: Optional[List[str]] = None,
    allowed_secret_prefixes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Fetch sanitized status for a job_id."""
    try:
        api = mcp_api(
            extra_hosts=allowed_provider_hosts,
            extra_secret_prefixes=allowed_secret_prefixes,
        )
        receipt = api.status(StatusRequest(job_id=job_id))
        return success_response(receipt.to_dict())
    except Exception as exc:
        return error_response(exc)
