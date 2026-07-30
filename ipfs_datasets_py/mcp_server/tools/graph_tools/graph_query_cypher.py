"""MCP tool: Cypher / cypher-lite query via persistent GraphService."""

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
    ensure_legacy_graph,
    legacy_target_from_driver,
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
    streaming=False,
    cancellable=True,
)
async def graph_query_cypher(
    query: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    storage_profile: Optional[str] = None,
    language: str = "cypher",
    max_rows: Optional[int] = None,
    budgets: Optional[Mapping[str, Any]] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    cancel_token: Optional[str] = None,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a Cypher (lite) query against an explicit graph target.

    Returns a canonical JSON-safe lifecycle result whose ``result`` field is
    a ``kg-query-envelope/v1`` payload (columns, rows, revision, cursor…).
    """
    op = "query"
    legacy_mode = bool(
        driver_url and target is None and tenant is None and graph_id is None and graph is None
    )
    if legacy_mode:
        target = legacy_target_from_driver(str(driver_url)).uri
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

    if not query:
        return error_envelope(
            op, "query text is required", code="INVALID_REQUEST", target=t
        )

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
        legacy_driver_url=str(driver_url) if legacy_mode else None,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    if legacy_mode:
        create_error = await ensure_legacy_graph(binding, t)
        if create_error is not None:
            return create_error

    # Cooperative cancellation: if a prior stream session was cancelled.
    if cancel_token:
        session = binding.streams.get(cancel_token)
        if session is not None and session.cancelled:
            return error_envelope(
                op,
                "operation cancelled",
                code="BUDGET_EXCEEDED",
                target=t,
                details={"cancel_token": cancel_token},
                request_id=request_id,
            )

    params: Dict[str, Any] = {
        "language": language or "cypher",
        "query": query,
        "text": query,
        "params": dict(parameters or {}),
    }
    if max_rows is not None:
        params["max_rows"] = int(max_rows)

    budget_map = dict(budgets or {})
    if max_rows is not None and "max_rows" not in budget_map:
        budget_map["max_rows"] = int(max_rows)

    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)

    try:
        result = await run_in_thread(
            binding.service.query,
            t,
            params=params,
            auth=auth_map,
            request_id=request_id,
            budgets=budget_map or None,
        )
        payload = json_safe_result(result)
        # Echo query for legacy callers.
        if payload.get("status") == "success" and isinstance(payload.get("result"), dict):
            payload["query"] = query
            payload["results"] = payload["result"].get("rows")
        return payload
    except Exception as exc:
        logger.exception("graph_query_cypher failed")
        return error_envelope(
            op, str(exc), code="QUERY_EXECUTION", target=t, request_id=request_id
        )
