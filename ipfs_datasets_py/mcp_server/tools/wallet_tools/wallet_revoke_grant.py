from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load, save


@tool_metadata(category="wallet_tools", mcp_description="Revoke a wallet grant and dependent access.")
async def wallet_revoke_grant(
    wallet_id: str,
    grant_id: str,
    actor_did: str,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Revoke an active grant and persist the updated snapshot."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        grant = svc.revoke_grant(wallet_id, grant_id=grant_id, actor_did=actor_did)
        snapshot_path = save(svc, wallet_root, wallet_id)
        return {
            "status": "success",
            "wallet_id": wallet_id,
            "grant": grant.to_dict(),
            "grant_id": grant.grant_id,
            "grant_status": grant.status,
            "snapshot_path": str(snapshot_path),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_revoke_grant failed: {exc}"}
