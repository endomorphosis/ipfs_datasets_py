from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.wallet.ucan import resource_for_record

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(category="wallet_tools", mcp_description="Create a bounded UCAN record grant.")
async def wallet_create_record_grant(
    wallet_id: str,
    record_id: str,
    issuer_did: str,
    audience_did: str,
    abilities: List[str],
    issuer_key_hex: Optional[str] = None,
    audience_key_hex: Optional[str] = None,
    purpose: str = "service_matching",
    output_types: Optional[List[str]] = None,
    user_presence_required: bool = False,
    expires_at: Optional[str] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Grant a delegate scoped record access without returning plaintext."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        caveats: Dict[str, Any] = {"purpose": purpose}
        if output_types is not None:
            caveats["output_types"] = list(output_types)
        if user_presence_required:
            caveats["user_presence_required"] = True
        grant = svc.create_grant(
            wallet_id=wallet_id,
            issuer_did=issuer_did,
            audience_did=audience_did,
            resources=[resource_for_record(wallet_id, record_id)],
            abilities=list(abilities),
            caveats=caveats,
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
        return {"status": "error", "message": f"wallet_create_record_grant failed: {exc}"}
