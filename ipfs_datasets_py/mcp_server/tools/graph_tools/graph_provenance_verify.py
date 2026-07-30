"""MCP tool: provenance verify — requires explicit GraphTarget."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_READ,
    DEFAULT_BRANCH,
    EFFECT_READ,
    declare_mcp_plus,
    error_envelope,
    load_snapshot_payload,
    resolve_target,
    wrap_specialized_result,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_READ,
    effects=[EFFECT_READ],
    resource_template="kg://{tenant}/{graph_id}",
)
async def graph_provenance_verify(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    provenance_jsonl: Optional[str] = None,
    kg_data: Optional[Dict[str, Any]] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify provenance for an explicit graph target."""
    op = "query"
    t, err = resolve_target(
        target=target,
        tenant=tenant,
        graph_id=graph_id,
        graph=graph,
        branch=branch,
        revision=revision,
        require_graph=True,
        default_branch=DEFAULT_BRANCH,
        operation=op,
    )
    if err is not None:
        return err

    data = kg_data
    resolved = t
    if data is None and provenance_jsonl is None:
        resolved, data, _ = await load_snapshot_payload(
            target=t.to_json_dict() if t else None,
            catalog_path=catalog_path,
            storage_path=storage_path,
            auth=auth,
            principal=principal,
            request_id=request_id,
            operation=op,
        )

    try:
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        manager = KnowledgeGraphManager()
        result = await manager.verify_provenance(
            provenance_jsonl=provenance_jsonl,
            kg_data=data,
        )
        if not isinstance(result, dict):
            result = {"status": "success", "valid": bool(result)}
        return wrap_specialized_result(
            op, target=resolved or t, payload=result, request_id=request_id
        )
    except Exception as exc:
        logger.exception("graph_provenance_verify failed")
        return error_envelope(
            op, str(exc), code="INTEGRITY", target=t, request_id=request_id
        )
