"""MCP tool: completion suggestions — requires explicit GraphTarget."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_QUERY,
    DEFAULT_BRANCH,
    EFFECT_QUERY,
    declare_mcp_plus,
    error_envelope,
    load_snapshot_payload,
    resolve_target,
    wrap_specialized_result,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_QUERY,
    effects=[EFFECT_QUERY],
    resource_template="kg://{tenant}/{graph_id}",
)
async def graph_complete_suggestions(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    kg_data: Optional[Dict[str, Any]] = None,
    min_score: float = 0.3,
    max_suggestions: int = 20,
    entity_id: Optional[str] = None,
    rel_type: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Suggest missing relationships for an explicit graph target."""
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
    if data is None:
        resolved, data, _ = await load_snapshot_payload(
            target=t.to_json_dict() if t else None,
            catalog_path=catalog_path,
            storage_path=storage_path,
            auth=auth,
            principal=principal,
            request_id=request_id,
            operation=op,
        )
        data = data or {"entities": [], "relationships": []}

    try:
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        manager = KnowledgeGraphManager()
        result = await manager.suggest_completions(
            kg_data=data,
            min_score=min_score,
            max_suggestions=max_suggestions,
            entity_id=entity_id,
            rel_type=rel_type,
        )
        if not isinstance(result, dict):
            result = {"status": "success", "suggestions": result}
        return wrap_specialized_result(
            op, target=resolved or t, payload=result, request_id=request_id
        )
    except Exception as exc:
        logger.exception("graph_complete_suggestions failed")
        return error_envelope(
            op, str(exc), code="INTERNAL", target=t, request_id=request_id
        )
