from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, save, service


@tool_metadata(category="wallet_tools", mcp_description="Create a wallet snapshot for UCAN-scoped data sharing.")
async def wallet_create(
    owner_did: str,
    controller_dids: Optional[List[str]] = None,
    approval_threshold: Optional[int] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a wallet and persist its initial snapshot.

    Args:
        owner_did: DID that owns the wallet.
        controller_dids: Optional controller DID list.
        approval_threshold: Optional governance threshold for sensitive operations.
        wallet_dir: Optional snapshot directory override.
        blob_dir: Optional encrypted blob directory override.

    Returns:
        Dictionary containing wallet identifiers and persisted snapshot path.
    """
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        controllers = list(controller_dids or [owner_did])
        if owner_did not in controllers:
            controllers = [owner_did, *controllers]
        governance_policy: Dict[str, Any] = {}
        if approval_threshold is not None:
            governance_policy = {
                "threshold": approval_threshold,
                "approver_dids": controllers,
            }
        svc = service(blob_root)
        wallet = svc.create_wallet(
            owner_did=owner_did,
            controller_dids=controllers,
            governance_policy=governance_policy,
        )
        snapshot_path = save(svc, wallet_root, wallet.wallet_id)
        return {
            "status": "success",
            "wallet_id": wallet.wallet_id,
            "owner_did": wallet.owner_did,
            "controller_dids": list(wallet.controller_dids),
            "manifest_head": wallet.manifest_head,
            "snapshot_path": str(snapshot_path),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_create failed: {exc}"}

