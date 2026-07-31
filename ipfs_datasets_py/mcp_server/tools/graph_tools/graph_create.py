"""MCP tool: create a knowledge graph via the server-owned GraphService."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_ADMIN,
    DEFAULT_BRANCH,
    EFFECT_ADMIN,
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
    ability=ABILITY_ADMIN,
    effects=[EFFECT_ADMIN],
    resource_template="kg://{tenant}/{graph_id}/branches/{branch}",
    mutates=True,
)
async def graph_create(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    storage_profile: Optional[str] = None,
    profile: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    params: Optional[Mapping[str, Any]] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    # Legacy no-op kwargs (ignored; kept so old call sites get a typed error).
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Create and register a graph identity on the persistent GraphService.

    Requires an explicit GraphTarget (``target=kg://…`` or ``tenant`` +
    ``graph_id``). Does **not** invent ambient process-local graphs.
    """
    op = "create"
    t, err = resolve_target(
        target=target,
        tenant=tenant,
        graph_id=graph_id,
        graph=graph,
        branch=branch,
        storage_profile=storage_profile,
        profile=profile,
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
    create_params: Dict[str, Any] = dict(params or {})
    if t.storage_profile and "storage_profile" not in create_params:
        create_params["storage_profile"] = t.storage_profile
    key = idempotency_key or f"mcp-create-{uuid.uuid4().hex}"
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)

    try:
        result = await run_in_thread(
            binding.service.create,
            t,
            idempotency_key=key,
            params=create_params or None,
            auth=auth_map,
            request_id=request_id,
        )
        return json_safe_result(result)
    except Exception as exc:
        logger.exception("graph_create failed")
        return error_envelope(
            op,
            str(exc),
            code="INTERNAL",
            target=t,
            request_id=request_id,
        )
