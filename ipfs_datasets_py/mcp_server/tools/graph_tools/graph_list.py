"""MCP tool: list graphs for a tenant via GraphService."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_LIST,
    EFFECT_READ,
    declare_mcp_plus,
    error_envelope,
    json_safe_result,
    resolve_auth,
    resolve_binding,
    resolve_target,
    run_in_thread,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_LIST,
    effects=[EFFECT_READ],
    resource_template="kg://{tenant}",
)
async def graph_list(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    params: Optional[Mapping[str, Any]] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """List graphs for an explicit tenant target."""
    op = "list"
    t, err = resolve_target(
        target=target,
        tenant=tenant,
        graph_id=graph_id,
        graph=graph,
        require_graph=False,
        for_list=True,
        operation=op,
    )
    if err is not None:
        return err

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)
    try:
        result = await run_in_thread(
            binding.service.list,
            t,
            params=dict(params or {}) or None,
            auth=auth_map,
            request_id=request_id,
        )
        return json_safe_result(result)
    except Exception as exc:
        logger.exception("graph_list failed")
        return error_envelope(
            op, str(exc), code="INTERNAL", target=t, request_id=request_id
        )
