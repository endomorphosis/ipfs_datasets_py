from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load_all, save


@tool_metadata(category="wallet_tools", mcp_description="Create analytics consent from an approved template.")
async def wallet_analytics_create_consent(
    wallet_id: str,
    actor_did: str,
    template_id: str,
    expires_at: Optional[str] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create analytics consent and persist the updated wallet snapshot."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load_all(wallet_root, blob_root)
        template = svc.analytics_templates[template_id]
        consent = svc.create_analytics_consent(
            wallet_id,
            actor_did=actor_did,
            template_id=template_id,
            allowed_record_types=list(template.allowed_record_types),
            allowed_derived_fields=list(template.allowed_derived_fields),
            expires_at=expires_at,
        )
        save(svc, wallet_root, wallet_id)
        return {"status": "success", "consent": consent.to_dict()}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_analytics_create_consent failed: {exc}"}
