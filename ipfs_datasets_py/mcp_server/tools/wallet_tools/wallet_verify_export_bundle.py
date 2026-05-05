from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, service


@tool_metadata(category="wallet_tools", mcp_description="Verify an encrypted export bundle hash and schema.")
async def wallet_verify_export_bundle(
    path: str,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify an export bundle without importing it."""
    try:
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = service(blob_root)
        bundle = json.loads(Path(path).read_text(encoding="utf-8"))
        computed_hash = svc.export_bundle_hash(bundle)
        embedded_hash = bundle.get("bundle_hash")
        hash_valid = isinstance(embedded_hash, str) and embedded_hash == computed_hash
        schema_valid = False
        schema_error = None
        if hash_valid:
            try:
                svc.validate_export_bundle_schema(bundle)
                schema_valid = True
            except Exception as exc:
                schema_error = str(exc)
        return {
            "status": "success",
            "valid": hash_valid and schema_valid,
            "hash_valid": hash_valid,
            "schema_valid": schema_valid,
            "bundle_id": bundle.get("bundle_id"),
            "bundle_hash": embedded_hash,
            "computed_hash": computed_hash,
            **({"schema_error": schema_error} if schema_error else {}),
        }
    except Exception as exc:
        return {"status": "error", "message": f"wallet_verify_export_bundle failed: {exc}"}
