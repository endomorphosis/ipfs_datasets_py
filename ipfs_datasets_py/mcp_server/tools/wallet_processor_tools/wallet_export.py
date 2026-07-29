"""MCP tool: module-level wallet_export AST surface (thin alias)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from .wallet_processor_export import wallet_processor_export


@tool_metadata(
    category="wallet_processor_tools",
    mcp_description=(
        "Bounded wallet dataset export. Default mode is finalized; "
        "provisional/raw modes are explicit. Does not sign or broadcast."
    ),
    timeout_seconds=120.0,
    io_intensive=True,
)
async def wallet_export(
    scope: str,
    chain: Dict[str, Any],
    output_dir: str,
    bounds: Optional[Dict[str, Any]] = None,
    records: Optional[List[Dict[str, Any]]] = None,
    formats: Optional[List[str]] = None,
    mode: str = "finalized",
    raw_payload_policy: str = "omitted",
    request_id: Optional[str] = None,
    allowed_provider_hosts: Optional[List[str]] = None,
    allowed_secret_prefixes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Export normalized wallet records (default finalized).

    This is the AST-visible ``wallet_export`` MCP entrypoint; it delegates to
    :func:`wallet_processor_export`.
    """
    return await wallet_processor_export(
        scope=scope,
        chain=chain,
        output_dir=output_dir,
        bounds=bounds,
        records=records,
        formats=formats,
        mode=mode,
        raw_payload_policy=raw_payload_policy,
        request_id=request_id,
        allowed_provider_hosts=allowed_provider_hosts,
        allowed_secret_prefixes=allowed_secret_prefixes,
    )
