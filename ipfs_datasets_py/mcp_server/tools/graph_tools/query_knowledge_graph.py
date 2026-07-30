"""MCP wrapper for knowledge graph querying via GraphService (KGP-019)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Union

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
    cancellable=True,
)
async def query_knowledge_graph(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    query: str = "",
    query_type: str = "scan",
    max_results: int = 100,
    include_metadata: bool = True,
    language: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    budgets: Optional[Dict[str, Any]] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    # Legacy kwargs accepted but not used for routing (service path only).
    manifest_cid: Optional[str] = None,
    ir_ops: Optional[List[Dict[str, Any]]] = None,
    budget_preset: Optional[str] = None,
    ipfs_backend: Optional[str] = None,
    car_fetch_mode: str = "auto",
) -> Dict[str, Any]:
    """Query a knowledge graph through the persistent GraphService.

    Requires an explicit GraphTarget. Results are canonical JSON-safe envelopes.
    """
    op = "query"
    # Allow graph_id alone as the short form when tenant is also supplied.
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

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    lang = language or (
        "scan" if query_type in {"ir", "scan", "node-scan", "nodes"} else query_type
    )
    params: Dict[str, Any] = {
        "language": lang,
        "query": query,
        "text": query,
        "params": dict(parameters or {}),
        "max_rows": int(max_results),
        "include_metadata": include_metadata,
    }
    if manifest_cid:
        params["manifest_cid"] = manifest_cid
    if ir_ops:
        params["ir_ops"] = ir_ops

    budget_map = dict(budgets or {})
    budget_map.setdefault("max_rows", int(max_results))
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)

    try:
        result = await run_in_thread(
            binding.service.query,
            t,
            params=params,
            auth=auth_map,
            request_id=request_id,
            budgets=budget_map,
        )
        return json_safe_result(result)
    except Exception as exc:
        logger.exception("query_knowledge_graph failed")
        return error_envelope(
            op, str(exc), code="QUERY_EXECUTION", target=t, request_id=request_id
        )
