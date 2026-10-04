"""MCP tool: resume a prior wallet processor job."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.processors.wallets.api import ResumeRequest

from ._helpers import (
    error_response,
    mcp_api,
    parse_bounds,
    success_response,
)


@tool_metadata(
    category="wallet_processor_tools",
    mcp_description=(
        "Resume a prior bounded wallet/ledger ingest job by job_id. "
        "Does not sign or broadcast."
    ),
    timeout_seconds=120.0,
    io_intensive=True,
)
async def wallet_processor_resume(
    job_id: str,
    bounds: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    allowed_provider_hosts: Optional[List[str]] = None,
    allowed_secret_prefixes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Resume a stored job through WalletProcessorAPI.resume."""
    try:
        api = mcp_api(
            extra_hosts=allowed_provider_hosts,
            extra_secret_prefixes=allowed_secret_prefixes,
        )
        result = await api.resume(
            ResumeRequest(
                job_id=job_id,
                bounds=parse_bounds(bounds),
                request_id=request_id,
            )
        )
        return success_response(result.to_dict())
    except Exception as exc:
        return error_response(exc)
