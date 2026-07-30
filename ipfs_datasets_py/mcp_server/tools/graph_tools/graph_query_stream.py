"""MCP tool: streaming query pages with cursor preservation (KGP-019)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_QUERY,
    DEFAULT_BRANCH,
    EFFECT_QUERY,
    EFFECT_STREAM,
    declare_mcp_plus,
    error_envelope,
    json_safe_result,
    resolve_auth,
    resolve_binding,
    resolve_target,
    run_in_thread,
    success_envelope,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_QUERY,
    effects=[EFFECT_QUERY, EFFECT_STREAM],
    resource_template="kg://{tenant}/{graph_id}",
    streaming=True,
    cancellable=True,
)
async def graph_query_stream(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    storage_profile: Optional[str] = None,
    query: Optional[str] = None,
    language: str = "scan",
    parameters: Optional[Dict[str, Any]] = None,
    page_size: int = 100,
    cursor: Optional[str] = None,
    max_rows: Optional[int] = None,
    budgets: Optional[Mapping[str, Any]] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Stream query results page-by-page with opaque revision-bound cursors.

    First call (no ``cursor``) runs the query and returns the first page plus
    a cursor for the next page. Subsequent calls with ``cursor`` resume from
    the process GraphService stream store without re-querying.
    """
    op = "query"

    # Resume existing cursor — still require target for tenant isolation.
    if cursor:
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

        binding, berr = resolve_binding(
            catalog_path=catalog_path,
            storage_path=storage_path,
            operation=op,
        )
        if berr is not None:
            return berr

        assert t is not None and binding is not None
        session = binding.streams.get(cursor)
        if session is None:
            return error_envelope(
                op,
                f"unknown or expired cursor: {cursor}",
                code="NOT_FOUND",
                target=t,
                details={"cursor": cursor},
                request_id=request_id,
            )
        # Tenant isolation on cursor resume.
        if session.tenant != t.tenant or session.graph_id != t.graph_id:
            return error_envelope(
                op,
                "cursor does not belong to the requested target",
                code="FORBIDDEN",
                target=t,
                details={"cursor": cursor},
                request_id=request_id,
            )
        auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)
        if auth_map and auth_map.get("tenant") and auth_map["tenant"] != session.tenant:
            return error_envelope(
                op,
                "cursor tenant not authorized for this principal",
                code="FORBIDDEN",
                target=t,
                request_id=request_id,
            )
        if auth_map and auth_map.get("principal") and session.principal:
            if str(auth_map["principal"]) != str(session.principal):
                return error_envelope(
                    op,
                    "cursor principal mismatch",
                    code="FORBIDDEN",
                    target=t,
                    request_id=request_id,
                )

        page = binding.streams.next_page(cursor, page_size=page_size)
        if page is None:
            return error_envelope(
                op, "cursor lost", code="NOT_FOUND", target=t, request_id=request_id
            )
        if page.get("cancelled"):
            return error_envelope(
                op,
                "stream cancelled",
                code="BUDGET_EXCEEDED",
                target=t,
                details={"cursor": cursor, "cancelled": True},
                request_id=request_id,
            )
        return success_envelope(
            op,
            target=t,
            result={
                "envelope_version": "kg-query-envelope/v1",
                "schema": page.get("schema") or "node-scan/v1",
                "columns": page["columns"],
                "rows": page["rows"],
                "row_count": page["row_count"],
                "offset": page["offset"],
                "page_index": page.get("page_index", 0),
                "exhausted": page["exhausted"],
                "cursor": page.get("cursor"),
                "revision": page.get("revision"),
                "streaming": True,
                "statistics": page.get("statistics") or {},
            },
            request_id=request_id,
        )

    # Fresh stream: require query target and run full query once.
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
        "query": query or "",
        "text": query or "",
        "params": dict(parameters or {}),
    }
    if max_rows is not None:
        params["max_rows"] = int(max_rows)
    budget_map = dict(budgets or {})
    if max_rows is not None:
        budget_map.setdefault("max_rows", int(max_rows))

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
    except Exception as exc:
        logger.exception("graph_query_stream failed")
        return error_envelope(
            op, str(exc), code="QUERY_EXECUTION", target=t, request_id=request_id
        )

    if not result.ok:
        return json_safe_result(result)

    payload = result.result or {}
    columns = list(payload.get("columns") or [])
    rows = list(payload.get("rows") or [])
    principal_s = None
    if auth_map:
        principal_s = auth_map.get("principal") or auth_map.get("subject")

    session = binding.streams.create(
        tenant=t.tenant,
        graph_id=t.graph_id,
        revision=payload.get("revision"),
        columns=columns,
        rows=rows,
        page_size=max(1, int(page_size)),
        language=language or "scan",
        query_text=query or "",
        statistics=payload.get("statistics") or {},
        schema=str(payload.get("schema") or "node-scan/v1"),
        principal=str(principal_s) if principal_s else None,
    )
    page = binding.streams.next_page(session.session_id, page_size=page_size)
    assert page is not None

    return success_envelope(
        op,
        target=result.target or t,
        result={
            "envelope_version": "kg-query-envelope/v1",
            "schema": page.get("schema") or payload.get("schema"),
            "columns": page["columns"],
            "rows": page["rows"],
            "row_count": page["row_count"],
            "offset": page["offset"],
            "page_index": page.get("page_index", 0),
            "exhausted": page["exhausted"],
            "cursor": page.get("cursor"),
            "revision": page.get("revision") or payload.get("revision"),
            "streaming": True,
            "statistics": page.get("statistics") or payload.get("statistics") or {},
            "total_row_count": len(rows),
        },
        request_id=request_id or result.request_id,
        authorization_receipt_ref=result.authorization_receipt_ref,
    )
