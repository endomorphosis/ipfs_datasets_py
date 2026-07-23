from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.wallet.ucan import invocation_from_token

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(category="wallet_tools", mcp_description="Create a bounded encrypted wallet export bundle.")
async def wallet_create_export_bundle(
    wallet_id: str,
    actor_did: str,
    actor_key_hex: Optional[str] = None,
    grant_id: Optional[str] = None,
    invocation_token: Optional[str] = None,
    record_ids: Optional[List[str]] = None,
    out_path: Optional[str] = None,
    include_proofs: bool = True,
    include_derived_artifacts: bool = True,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an encrypted export descriptor without exposing plaintext."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        requested_ids = list(record_ids) if record_ids is not None else None
        if invocation_token:
            bundle = svc.create_export_bundle_with_invocation(
                wallet_id,
                actor_did=actor_did,
                invocation=invocation_from_token(invocation_token),
                actor_secret=key_from_optional_hex(actor_key_hex),
                record_ids=requested_ids,
                include_proofs=include_proofs,
                include_derived_artifacts=include_derived_artifacts,
            )
        else:
            bundle = svc.create_export_bundle(
                wallet_id,
                actor_did=actor_did,
                grant_id=grant_id,
                record_ids=requested_ids,
                include_proofs=include_proofs,
                include_derived_artifacts=include_derived_artifacts,
            )
        result: Dict[str, Any] = {
            "status": "success",
            "wallet_id": wallet_id,
            "bundle": bundle,
            "bundle_id": bundle["bundle_id"],
            "bundle_hash": bundle["bundle_hash"],
            "record_count": len(bundle["records"]),
            "proof_count": len(bundle["proofs"]),
            "derived_artifact_count": len(bundle["derived_artifacts"]),
        }
        if out_path:
            output = Path(out_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(bundle, sort_keys=True, indent=2), encoding="utf-8")
            result["out_path"] = str(output)
        snapshot_path = save(svc, wallet_root, wallet_id)
        result["snapshot_path"] = str(snapshot_path)
        return result
    except Exception as exc:
        return {"status": "error", "message": f"wallet_create_export_bundle failed: {exc}"}
