from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(category="wallet_tools", mcp_description="Add an encrypted location record to a wallet.")
async def wallet_add_location(
    wallet_id: str,
    actor_did: str,
    lat: float,
    lon: float,
    actor_key_hex: Optional[str] = None,
    source: str = "user",
    accuracy_m: Optional[float] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Encrypt and store a location record in a wallet snapshot."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        actor_secret = key_from_optional_hex(actor_key_hex)
        if actor_secret is not None:
            svc.set_principal_secret(actor_did, actor_secret)
        record = svc.add_location(
            wallet_id,
            lat=lat,
            lon=lon,
            actor_did=actor_did,
            source=source,
            accuracy_m=accuracy_m,
        )
        snapshot_path = save(svc, wallet_root, wallet_id)
        return {
            "status": "success",
            "wallet_id": wallet_id,
            "record_id": record.record_id,
            "version_id": record.current_version_id,
            "snapshot_path": str(snapshot_path),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_add_location failed: {exc}"}
