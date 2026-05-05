from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.wallet.ucan import invocation_to_token, resource_for_record

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(category="wallet_tools", mcp_description="Issue a signed wallet UCAN invocation for a record grant.")
async def wallet_issue_record_invocation(
    wallet_id: str,
    record_id: str,
    grant_id: str,
    actor_did: str,
    ability: str,
    actor_key_hex: Optional[str] = None,
    purpose: Optional[str] = None,
    output_types: Optional[List[str]] = None,
    user_present: bool = False,
    expires_at: Optional[str] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Issue a signed invocation token for a scoped record capability."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        caveats: Dict[str, Any] = {}
        if purpose is not None:
            caveats["purpose"] = purpose
        if output_types is not None:
            caveats["output_types"] = list(output_types)
        if user_present:
            caveats["user_present"] = True
        invocation = svc.issue_invocation(
            wallet_id,
            grant_id=grant_id,
            actor_did=actor_did,
            resource=resource_for_record(wallet_id, record_id),
            ability=ability,
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
        return {"status": "error", "message": f"wallet_issue_record_invocation failed: {exc}"}
