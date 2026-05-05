from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.wallet.ucan import resource_for_export

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(category="wallet_tools", mcp_description="Create a bounded encrypted export grant.")
async def wallet_create_export_grant(
    wallet_id: str,
    record_ids: List[str],
    issuer_did: str,
    audience_did: str,
    issuer_key_hex: Optional[str] = None,
    audience_key_hex: Optional[str] = None,
    purpose: str = "user_export",
    expires_at: Optional[str] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Grant a delegate access to create encrypted export bundles only."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        grant = svc.create_grant(
            wallet_id=wallet_id,
            issuer_did=issuer_did,
            audience_did=audience_did,
            resources=[resource_for_export(wallet_id)],
            abilities=["export/create"],
            caveats={
                "purpose": purpose,
                "record_ids": list(record_ids),
                "output_types": ["encrypted_export_bundle"],
            },
            expires_at=expires_at,
            issuer_secret=key_from_optional_hex(issuer_key_hex),
            audience_secret=key_from_optional_hex(audience_key_hex),
        )
        snapshot_path = save(svc, wallet_root, wallet_id)
        return {
            "status": "success",
            "wallet_id": wallet_id,
            "grant": grant.to_dict(),
            "grant_id": grant.grant_id,
            "snapshot_path": str(snapshot_path),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_create_export_grant failed: {exc}"}
