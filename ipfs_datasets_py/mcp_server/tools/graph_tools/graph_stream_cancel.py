"""MCP tool: cancel an in-flight stream / cursor session."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_QUERY,
    DEFAULT_BRANCH,
    EFFECT_CANCEL,
    declare_mcp_plus,
    error_envelope,
    resolve_auth,
    resolve_binding,
    resolve_target,
    success_envelope,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_QUERY,
    effects=[EFFECT_CANCEL],
    resource_template="kg://{tenant}/{graph_id}",
    streaming=True,
    cancellable=True,
)
async def graph_stream_cancel(
    cursor: Optional[str] = None,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    session_id: Optional[str] = None,
    reason: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cancel a streaming query session identified by cursor / session_id.

    Requires an explicit target so cancellation cannot cross tenants without
    authorization.
    """
    op = "query"
    sid = cursor or session_id
    if not sid:
        return error_envelope(
            op,
            "cursor or session_id is required",
            code="INVALID_REQUEST",
        )

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

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    session = binding.streams.get(sid)
    if session is None:
        return error_envelope(
            op,
            f"unknown cursor/session: {sid}",
            code="NOT_FOUND",
            target=t,
            details={"cursor": sid},
            request_id=request_id,
        )
    if session.tenant != t.tenant or session.graph_id != t.graph_id:
        return error_envelope(
            op,
            "cursor does not belong to the requested target",
            code="FORBIDDEN",
            target=t,
            request_id=request_id,
        )

    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)
    if auth_map and auth_map.get("principal") and session.principal:
        if str(auth_map["principal"]) != str(session.principal):
            return error_envelope(
                op,
                "not authorized to cancel this stream",
                code="FORBIDDEN",
                target=t,
                request_id=request_id,
            )

    ok = binding.streams.cancel(sid)
    return success_envelope(
        op,
        target=t,
        result={
            "cancelled": bool(ok),
            "cursor": sid,
            "session_id": sid,
            "reason": reason,
        },
        request_id=request_id,
    )
