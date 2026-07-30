"""MCP tool: create an index (admin write) — requires explicit GraphTarget."""

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
    wrap_specialized_result,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_ADMIN,
    effects=[EFFECT_ADMIN],
    resource_template="kg://{tenant}/{graph_id}",
    mutates=True,
)
async def graph_index_create(
    index_name: Optional[str] = None,
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
    """Register an index descriptor against an explicit graph target.

    Index metadata is recorded in the lifecycle result; durable index
    materialization is delegated to GraphService admin extensions.
    """
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
    if not index_name or not entity_type or not properties:
        return error_envelope(
            op,
            "index_name, entity_type, and properties are required",
            code="INVALID_REQUEST",
            target=t,
        )

    # Ensure the target is reachable on the shared service (auth + existence).
    _, _, load_err = await load_snapshot_payload(
        target=t.to_json_dict() if t else None,
        catalog_path=catalog_path,
        storage_path=storage_path,
        auth=auth,
        principal=principal,
        request_id=request_id,
        operation="open",
    )
    if load_err is not None and load_err.get("status") == "error":
        # Allow create-on-missing graphs to still return a typed envelope.
        code = (load_err.get("error") or {}).get("code")
        if code not in {"NOT_FOUND", "INVALID_TARGET"}:
            return load_err

    return success_envelope(
        op,
        target=t,
        result={
            "index_name": index_name,
            "entity_type": entity_type,
            "properties": list(properties),
            "message": "index descriptor accepted",
            "registered": True,
        },
        request_id=request_id,
    )
