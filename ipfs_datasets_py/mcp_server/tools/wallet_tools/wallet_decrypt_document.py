from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
from ipfs_datasets_py.wallet.ucan import invocation_from_token

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(category="wallet_tools", mcp_description="Decrypt a document with owner, grant, or invocation access.")
async def wallet_decrypt_document(
    wallet_id: str,
    record_id: str,
    actor_did: str,
    actor_key_hex: Optional[str] = None,
    grant_id: Optional[str] = None,
    invocation_token: Optional[str] = None,
    out_path: Optional[str] = None,
    include_text: bool = False,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Decrypt a wallet document; plaintext is returned only when explicitly requested."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        actor_secret = key_from_optional_hex(actor_key_hex)
        if invocation_token:
            plaintext = svc.decrypt_record_with_invocation(
                wallet_id,
                record_id,
                actor_did=actor_did,
                invocation=invocation_from_token(invocation_token),
                actor_secret=actor_secret,
            )
        else:
            plaintext = svc.decrypt_record(
                wallet_id,
                record_id,
                actor_did=actor_did,
                grant_id=grant_id,
                actor_secret=actor_secret,
            )
        result: Dict[str, Any] = {
            "status": "success",
            "wallet_id": wallet_id,
            "record_id": record_id,
            "size_bytes": len(plaintext),
        }
        if out_path:
            output = Path(out_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(plaintext)
            result["out_path"] = str(output)
        if include_text:
            result["text"] = plaintext.decode("utf-8", errors="replace")
        snapshot_path = save(svc, wallet_root, wallet_id)
        result["snapshot_path"] = str(snapshot_path)
        return result
    except Exception as exc:
        return {"status": "error", "message": f"wallet_decrypt_document failed: {exc}"}
