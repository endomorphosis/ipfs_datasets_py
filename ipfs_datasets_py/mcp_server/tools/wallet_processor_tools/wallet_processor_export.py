"""MCP tool: bounded wallet dataset export."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.processors.wallets.api import (
    ExportMode,
    WalletExportRequest,
)
from ipfs_datasets_py.processors.wallets.export import ExportFormat
from ipfs_datasets_py.processors.wallets.models import RawPayloadPolicy

from ._helpers import (
    error_response,
    mcp_api,
    parse_bounds,
    parse_chain,
    success_response,
)


@tool_metadata(
    category="wallet_processor_tools",
    mcp_description=(
        "Bounded wallet dataset export. Default mode is finalized; "
        "provisional and raw modes must be requested explicitly. "
        "Does not sign or broadcast."
    ),
    timeout_seconds=120.0,
    io_intensive=True,
)
async def wallet_processor_export(
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
    """Export records through WalletProcessorAPI.wallet_export.

    Args:
        scope: Export scope label.
        chain: ChainRef mapping.
        output_dir: Destination directory for partitions/manifest.
        bounds: Finite export bounds (max_items caps record count).
        records: Optional pre-normalized record dicts (no raw secrets).
        formats: Export formats (default jsonl).
        mode: finalized (default) | provisional | raw.
        raw_payload_policy: omitted | referenced | separately_encrypted.
        request_id: Optional correlation id.
        allowed_provider_hosts: Unused for pure export; reserved for parity.
        allowed_secret_prefixes: Unused for pure export; reserved for parity.

    Returns:
        Sanitized export receipt.
    """
    try:
        api = mcp_api(
            extra_hosts=allowed_provider_hosts,
            extra_secret_prefixes=allowed_secret_prefixes,
        )
        fmt_tuple = tuple(
            ExportFormat(f) for f in (formats or [ExportFormat.JSONL.value])
        )
        request = WalletExportRequest(
            scope=scope,
            chain=parse_chain(chain),
            output_dir=output_dir,
            bounds=parse_bounds(bounds),
            request_id=request_id,
            records=tuple(records or ()),
            formats=fmt_tuple,
            mode=ExportMode(str(mode).lower()),
            raw_payload_policy=RawPayloadPolicy(str(raw_payload_policy).lower()),
        )
        result = await api.wallet_export(request)
        return success_response(result.to_dict())
    except Exception as exc:
        return error_response(exc)
