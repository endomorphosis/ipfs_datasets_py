from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load_all, parse_fields, save


@tool_metadata(category="wallet_tools", mcp_description="Submit derived analytics fields under an active consent.")
async def wallet_analytics_contribute(
    wallet_id: str,
    actor_did: str,
    consent_id: str,
    template_id: str,
    fields: Dict[str, Any],
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an analytics contribution and persist the wallet snapshot."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load_all(wallet_root, blob_root)
        contribution = svc.create_analytics_contribution(
            wallet_id,
            actor_did=actor_did,
            consent_id=consent_id,
            template_id=template_id,
            fields=parse_fields(fields),
        )
        save(svc, wallet_root, wallet_id)
        return {"status": "success", "contribution": contribution.to_dict()}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_analytics_contribute failed: {exc}"}
