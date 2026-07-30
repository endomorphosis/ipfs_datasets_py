"""MCP tool: hybrid / scan search via persistent GraphService."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_QUERY,
    DEFAULT_BRANCH,
    EFFECT_QUERY,
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
    ability=ABILITY_QUERY,
    effects=[EFFECT_QUERY],
    resource_template="kg://{tenant}/{graph_id}",
)
async def graph_search_hybrid(
    query: Optional[str] = None,
    search_type: str = "hybrid",
    limit: int = 10,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    storage_profile: Optional[str] = None,
    language: str = "scan",
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Bounded hybrid/scan query against an explicit graph target."""
    op = "query"
    t, err = resolve_target(
        target=target,
        tenant=tenant,
        graph_id=graph_id,
        graph=graph,
        branch=branch,
        revision=revision,
        storage_profile=storage_profile,
        require_graph=True,
        default_branch=DEFAULT_BRANCH,
        operation=op,
    )
    if err is not None:
        return err

    if query is None:
        query = ""

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    params: Dict[str, Any] = {
        "language": language or "scan",
        "query": query,
        "text": query,
        "search_type": search_type,
        "max_rows": int(limit),
    }
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)

    try:
        result = await run_in_thread(
            binding.service.query,
            t,
            params=params,
            auth=auth_map,
            request_id=request_id,
            budgets={"max_rows": int(limit)},
        )
        payload = json_safe_result(result)
        if payload.get("status") == "success" and isinstance(payload.get("result"), dict):
            payload["query"] = query
            payload["search_type"] = search_type
            payload["results"] = payload["result"].get("rows")
            payload["count"] = payload["result"].get("row_count")
        return payload
    except Exception as exc:
        logger.exception("graph_search_hybrid failed")
        return error_envelope(
            op, str(exc), code="QUERY_EXECUTION", target=t, request_id=request_id
        )
