"""MCP tool: add a constraint — requires explicit GraphTarget."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Union

from ._bridge import (
    ABILITY_ADMIN,
    DEFAULT_BRANCH,
    EFFECT_ADMIN,
    declare_mcp_plus,
    error_envelope,
    load_snapshot_payload,
    resolve_target,
    success_envelope,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_ADMIN,
    effects=[EFFECT_ADMIN],
    resource_template="kg://{tenant}/{graph_id}",
    mutates=True,
)
async def graph_constraint_add(
    constraint_name: Optional[str] = None,
    constraint_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    properties: Optional[List[str]] = None,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a constraint descriptor on an explicit graph target."""
    op = "write"
    t, err = resolve_target(
        target=target,
        tenant=tenant,
        graph_id=graph_id,
        graph=graph,
        branch=branch,
        require_graph=True,
        default_branch=DEFAULT_BRANCH,
        operation=op,
    )
    if err is not None:
        return err
    if not constraint_name or not constraint_type or not entity_type or not properties:
        return error_envelope(
            op,
            "constraint_name, constraint_type, entity_type, and properties are required",
            code="INVALID_REQUEST",
            target=t,
        )

    await load_snapshot_payload(
        target=t.to_json_dict() if t else None,
        catalog_path=catalog_path,
        storage_path=storage_path,
        auth=auth,
        principal=principal,
        request_id=request_id,
        operation="open",
        require_target=True,
    )

    return success_envelope(
        op,
        target=t,
        result={
            "constraint_name": constraint_name,
            "constraint_type": constraint_type,
            "entity_type": entity_type,
            "properties": list(properties),
            "message": "constraint descriptor accepted",
            "registered": True,
        },
        request_id=request_id,
    )
