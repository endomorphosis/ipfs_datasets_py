from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.wallet.ucan import invocation_to_token, resource_for_export

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(category="wallet_tools", mcp_description="Issue a signed wallet UCAN invocation for encrypted export.")
async def wallet_issue_export_invocation(
    wallet_id: str,
    grant_id: str,
    actor_did: str,
    actor_key_hex: Optional[str] = None,
    record_ids: Optional[List[str]] = None,
    purpose: str = "user_export",
    expires_at: Optional[str] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue a signed export/create invocation token."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        caveats: Dict[str, Any] = {
            "purpose": purpose,
            "output_types": ["encrypted_export_bundle"],
        }
        if record_ids is not None:
            caveats["record_ids"] = list(record_ids)
        invocation = svc.issue_invocation(
            wallet_id,
            grant_id=grant_id,
            actor_did=actor_did,
            resource=resource_for_export(wallet_id),
            ability="export/create",
            actor_secret=key_from_optional_hex(actor_key_hex),
            caveats=caveats,
            expires_at=expires_at,
        )
        snapshot_path = save(svc, wallet_root, wallet_id)
        return {
            "status": "success",
            "wallet_id": wallet_id,
            "invocation": invocation.to_dict(),
            "invocation_token": invocation_to_token(invocation),
            "snapshot_path": str(snapshot_path),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_issue_export_invocation failed: {exc}"}
