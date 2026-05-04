from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load


@tool_metadata(category="wallet_tools", mcp_description="List records stored in a wallet snapshot.")
async def wallet_list_records(
    wallet_id: str,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """List wallet records with IDs, types, and statuses."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load(wallet_root, blob_root, wallet_id)
        records = [
            record.to_dict()
            for record in sorted(svc.records.values(), key=lambda item: item.record_id)
            if record.wallet_id == wallet_id
        ]
        return {"status": "success", "wallet_id": wallet_id, "records": records}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_list_records failed: {exc}"}

