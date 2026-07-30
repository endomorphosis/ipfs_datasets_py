"""MCP tool: add a relationship via GraphService write (persistent)."""

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
async def graph_add_relationship(
    source_id: Optional[str] = None,
    target_id: Optional[str] = None,
    relationship_type: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    storage_profile: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    transaction_id: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    # Avoid collision: relationship end node is target_id; graph target is `target`.
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a relationship on a named graph through the shared GraphService."""
    op = "write"
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

    if not source_id or not target_id or not relationship_type:
        return error_envelope(
            op,
            "source_id, target_id, and relationship_type are required",
            code="INVALID_REQUEST",
            target=t,
        )

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    rel: Dict[str, Any] = {
        "source": source_id,
        "target": target_id,
        "type": relationship_type,
        "source_id": source_id,
        "target_id": target_id,
        "relationship_type": relationship_type,
    }
    if properties:
        rel["properties"] = properties

    params: Dict[str, Any] = {"relationships": [rel]}
    if transaction_id:
        params["transaction_id"] = transaction_id

    key = idempotency_key or f"mcp-add-rel-{uuid.uuid4().hex}"
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)

    try:
        result = await run_in_thread(
            binding.service.write,
            t,
            idempotency_key=key,
            params=params,
            auth=auth_map,
            request_id=request_id,
        )
        payload = json_safe_result(result)
        if payload.get("status") == "success":
            payload.setdefault("source_id", source_id)
            payload.setdefault("target_id", target_id)
            payload.setdefault("relationship_type", relationship_type)
        return payload
    except Exception as exc:
        logger.exception("graph_add_relationship failed")
        return error_envelope(
            op, str(exc), code="INTERNAL", target=t, request_id=request_id
        )
