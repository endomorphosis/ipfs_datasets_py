from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

from ._helpers import aggregate_result_summary, default_blob_dir, default_wallet_dir, load_all, save_all


@tool_metadata(category="wallet_tools", mcp_description="Run a private aggregate count across wallet analytics contributions.")
async def wallet_analytics_private_count(
    wallet_id: str,
    template_id: str,
    epsilon: Optional[float] = None,
    min_cohort_size: Optional[int] = None,
    budget_key: Optional[str] = None,
    budget_limit: Optional[float] = None,
    actor_did: str = "did:service:mcp-wallet-tools",
    wallet_dir: Optional[str] = None,
    blob_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a private aggregate count and persist the participating wallet snapshots."""
    try:
        wallet_root = Path(wallet_dir) if wallet_dir else default_wallet_dir()
        blob_root = Path(blob_dir) if blob_dir else default_blob_dir()
        svc = load_all(wallet_root, blob_root)
        result = svc.run_aggregate_count(
            template_id,
            min_cohort_size=min_cohort_size,
            epsilon=epsilon,
            budget_key=budget_key,
            budget_limit=budget_limit,
            actor_did=actor_did,
        )
        participating_wallet_ids = [
            consent.wallet_id
            for consent in svc.analytics_consents.values()
            if consent.template_id == template_id
        ]
        save_all(svc, wallet_root, participating_wallet_ids or [wallet_id])
        return {"status": "success", **aggregate_result_summary(result)}
    except Exception as exc:
        return {"status": "error", "message": f"wallet_analytics_private_count failed: {exc}"}
