from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load_all, save


@tool_metadata(category="wallet_tools", mcp_description="Import encrypted descriptors from a verified export bundle.")
async def wallet_import_export_bundle(
    path: str,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge an encrypted export bundle into existing wallet snapshots."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load_all(wallet_root, blob_root)
        bundle = json.loads(Path(path).read_text(encoding="utf-8"))
        result = svc.import_export_bundle(bundle)
        snapshot_path = save(svc, wallet_root, result["wallet_id"])
        return {"status": "success", **result, "snapshot_path": str(snapshot_path)}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_import_export_bundle failed: {exc}"}
