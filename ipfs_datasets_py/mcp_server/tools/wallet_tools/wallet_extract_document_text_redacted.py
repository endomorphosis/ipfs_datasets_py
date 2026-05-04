from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, key_from_optional_hex, load, save


@tool_metadata(
    category="wallet_tools",
    mcp_description="Extract text from an encrypted wallet document and return only redacted text.",
)
async def wallet_extract_document_text_redacted(
    wallet_id: str,
    record_id: str,
    actor_did: str,
    actor_key_hex: Optional[str] = None,
    grant_id: Optional[str] = None,
    max_chars: int = 20_000,
    max_bytes: int = 200_000,
    use_ocr: bool = True,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Run wallet-bound document text extraction and persist the redacted artifact."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        result = svc.extract_document_text_with_redaction(
            wallet_id,
            record_id,
            actor_did=actor_did,
            actor_secret=key_from_optional_hex(actor_key_hex),
            grant_id=grant_id,
            max_chars=max_chars,
            max_bytes=max_bytes,
            use_ocr=use_ocr,
        )
        snapshot_path = save(svc, wallet_root, wallet_id)
        return {
            "status": "success",
            "wallet_id": wallet_id,
            "artifact": result["artifact"].to_dict(),
            "output": result["output"],
            "snapshot_path": str(snapshot_path),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_extract_document_text_redacted failed: {exc}"}
