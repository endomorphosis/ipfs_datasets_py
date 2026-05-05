from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load_all


@tool_metadata(category="wallet_tools", mcp_description="Verify encrypted blob availability for an export bundle.")
async def wallet_export_bundle_storage(
    path: str,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Check that encrypted blobs referenced by a bundle are available."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load_all(wallet_root, blob_root)
        bundle = json.loads(Path(path).read_text(encoding="utf-8"))
        return {"status": "success", **svc.verify_export_bundle_storage(bundle)}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_export_bundle_storage failed: {exc}"}
