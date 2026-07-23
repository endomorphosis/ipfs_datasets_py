from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import default_blob_dir, default_wallet_dir, load_all, save


@tool_metadata(category="wallet_tools", mcp_description="Register an analytics template for private aggregate workflows.")
async def wallet_analytics_create_template(
    wallet_id: str,
    template_id: str,
    title: str,
    purpose: str,
    created_by: str,
    allowed_record_types: List[str],
    allowed_derived_fields: List[str],
    min_cohort_size: int = 10,
    epsilon_budget: float = 1.0,
    expires_at: Optional[str] = None,
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create and persist an analytics template."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load_all(wallet_root, blob_root)
        svc._wallet(wallet_id)
        template = svc.create_analytics_template(
            template_id=template_id,
            title=title,
            purpose=purpose,
            allowed_record_types=list(allowed_record_types),
            allowed_derived_fields=list(allowed_derived_fields),
            aggregation_policy={
                "min_cohort_size": min_cohort_size,
                "epsilon_budget": epsilon_budget,
                "duplicate_policy": "reject_by_nullifier",
            },
            created_by=created_by,
            expires_at=expires_at,
        )
        save(svc, wallet_root, wallet_id)
        return {"status": "success", "template": template.to_dict()}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_analytics_create_template failed: {exc}"}
