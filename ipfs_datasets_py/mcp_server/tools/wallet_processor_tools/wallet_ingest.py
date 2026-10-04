"""MCP tool: bounded wallet-centric ingest."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.processors.wallets.api import WalletIngestRequest
from ipfs_datasets_py.processors.wallets.export import ExportFormat

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
        "Bounded wallet-centric public-ledger ingest. Requires finite bounds. "
        "Provider URLs and secrets must match the untrusted MCP allowlist. "
        "Does not sign or broadcast."
    ),
    timeout_seconds=120.0,
    io_intensive=True,
)
async def wallet_ingest(
    scope: str,
    chain: Dict[str, Any],
    bounds: Optional[Dict[str, Any]] = None,
    family: Optional[str] = None,
    request_id: Optional[str] = None,
    cursor: Optional[str] = None,
    provider_url: Optional[str] = None,
    secret_reference: Optional[str] = None,
    export_dir: Optional[str] = None,
    export_formats: Optional[List[str]] = None,
    store_raw_payloads: bool = False,
    safety_depth: int = 0,
    allowed_provider_hosts: Optional[List[str]] = None,
    allowed_secret_prefixes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run a bounded wallet-centric ingest via WalletProcessorAPI.

    Args:
        scope: Wallet/account scope identity (required, finite).
        chain: ChainRef mapping (namespace, network, chain_id, genesis_hash).
        bounds: Finite scan bounds (items/pages/requests/bytes/time/retries).
        family: Optional processor family hint (not used for injection).
        request_id: Optional correlation id.
        cursor: Optional provider continuation hint.
        provider_url: Only accepted when host is on the untrusted allowlist.
        secret_reference: Opaque resolver URI; must match allowlisted prefix.
        export_dir: Optional directory for mid-run export.
        export_formats: Optional list of export formats.
        store_raw_payloads: Explicit opt-in for raw payload storage.
        safety_depth: Finality safety depth for checkpoints.
        allowed_provider_hosts: Additional allowlist hosts for this call.
        allowed_secret_prefixes: Additional secret reference prefixes.

    Returns:
        Sanitized ingest receipt (no wallet payloads or secrets).
    """
    try:
        api = mcp_api(
            extra_hosts=allowed_provider_hosts,
            extra_secret_prefixes=allowed_secret_prefixes,
        )
        formats = tuple(
            ExportFormat(f) for f in (export_formats or ())
        )
        request = WalletIngestRequest(
            scope=scope,
            chain=parse_chain(chain),
            bounds=parse_bounds(bounds),
            family=family,
            request_id=request_id,
            cursor=cursor,
            provider_url=provider_url,
            secret_reference=secret_reference,
            export_formats=formats,
            export_dir=export_dir,
            store_raw_payloads=bool(store_raw_payloads),
            safety_depth=int(safety_depth or 0),
        )
        result = await api.wallet_ingest(request)
        return success_response(result.to_dict())
    except Exception as exc:
        return error_response(exc)
