"""MCP tool: commit_tx on the server-owned GraphService."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_WRITE,
    DEFAULT_BRANCH,
    EFFECT_WRITE,
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
    ability=ABILITY_WRITE,
    effects=[EFFECT_WRITE],
    resource_template="kg://{tenant}/{graph_id}/branches/{branch}",
    mutates=True,
)
async def graph_transaction_commit(
    transaction_id: Optional[str] = None,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    storage_profile: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    params: Optional[Mapping[str, Any]] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit a previously begun transaction on the shared GraphService."""
    op = "commit_tx"
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
        storage_profile=storage_profile,
        require_graph=True,
        default_branch=DEFAULT_BRANCH,
        operation=op,
    )
    if err is not None:
        return err

    if not transaction_id:
        return error_envelope(
            op,
            "transaction_id is required",
            code="INVALID_REQUEST",
            target=t,
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
    p: Dict[str, Any] = dict(params or {})
    p["transaction_id"] = transaction_id
    key = idempotency_key or f"mcp-commit-{uuid.uuid4().hex}"
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)

    try:
        result = await run_in_thread(
            binding.service.commit_tx,
            t,
            idempotency_key=key,
            params=p,
            auth=auth_map,
            request_id=request_id,
        )
        payload = json_safe_result(result)
        if payload.get("status") == "success":
            payload.setdefault(
                "transaction_id", (payload.get("result") or {}).get("transaction_id")
            )
        return payload
    except Exception as exc:
        logger.exception("graph_transaction_commit failed")
        return error_envelope(
            op, str(exc), code="INTERNAL", target=t, request_id=request_id
        )
