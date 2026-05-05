from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load


@tool_metadata(category="wallet_tools", mcp_description="List wallet grant receipts visible to a recipient.")
async def wallet_grant_receipts(
    wallet_id: str,
    audience_did: Optional[str] = None,
    status_filter: str = "all",
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """List active or revoked grant receipts."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        normalized_status = None if status_filter == "all" else status_filter
        receipts = [
            receipt.to_dict()
            for receipt in svc.list_grant_receipts(
                wallet_id,
                audience_did=audience_did,
                status=normalized_status,
            )
        ]
        return {"status": "success", "wallet_id": wallet_id, "receipts": receipts}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_grant_receipts failed: {exc}"}
