from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load, save


@tool_metadata(category="wallet_tools", mcp_description="Create a safe public-input location-region proof receipt.")
async def wallet_create_location_region_proof(
    wallet_id: str,
    record_id: str,
    actor_did: str,
    region_id: str,
    actor_key_hex: Optional[str] = None,
    grant_id: Optional[str] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a location-region proof receipt and persist the wallet snapshot."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        if actor_key_hex:
            svc.set_principal_secret(actor_did, bytes.fromhex(actor_key_hex))
        receipt = svc.create_location_region_proof(
            wallet_id,
            record_id,
            actor_did=actor_did,
            region_id=region_id,
            grant_id=grant_id,
        )
        snapshot_path = save(svc, wallet_root, wallet_id)
        return {
            "status": "success",
            "wallet_id": wallet_id,
            "proof": receipt.to_dict(),
            "snapshot_path": str(snapshot_path),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_create_location_region_proof failed: {exc}"}
