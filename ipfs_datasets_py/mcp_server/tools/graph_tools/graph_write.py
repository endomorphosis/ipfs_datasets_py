"""MCP tool: generic write mutations via GraphService."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Mapping, Optional, Union

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
async def graph_write(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    storage_profile: Optional[str] = None,
    entities: Optional[List[Dict[str, Any]]] = None,
    relationships: Optional[List[Dict[str, Any]]] = None,
    delete_entity_ids: Optional[List[str]] = None,
    transaction_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    params: Optional[Mapping[str, Any]] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage/commit entity and relationship mutations on an explicit target."""
    op = "write"
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

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    p: Dict[str, Any] = dict(params or {})
    if entities is not None:
        p["entities"] = entities
    if relationships is not None:
        p["relationships"] = relationships
    if delete_entity_ids is not None:
        p["delete_entity_ids"] = delete_entity_ids
    if transaction_id:
        p["transaction_id"] = transaction_id

    key = idempotency_key or f"mcp-write-{uuid.uuid4().hex}"
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)

    try:
        result = await run_in_thread(
            binding.service.write,
            t,
            idempotency_key=key,
            params=p,
            auth=auth_map,
            request_id=request_id,
        )
        return json_safe_result(result)
    except Exception as exc:
        logger.exception("graph_write failed")
        return error_envelope(
            op, str(exc), code="INTERNAL", target=t, request_id=request_id
        )
