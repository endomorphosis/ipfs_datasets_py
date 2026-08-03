"""MCP tool: distributed query — routes through GraphService with explicit target."""

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
async def graph_distributed_execute(
    query: Optional[str] = None,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    revision: Optional[str] = None,
    num_partitions: int = 4,
    partition_strategy: str = "hash",
    parallel: bool = False,
    explain: bool = False,
    language: str = "cypher",
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a query against an explicit target (partition hints recorded)."""
    op = "query"
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
    if not query:
        return error_envelope(
            op, "query is required", code="INVALID_REQUEST", target=t
        )

    binding, berr = resolve_binding(
        catalog_path=catalog_path,
        storage_path=storage_path,
        operation=op,
    )
    if berr is not None:
        return berr

    assert t is not None and binding is not None
    params = {
        "language": language or "cypher",
        "query": query,
        "text": query,
        "num_partitions": num_partitions,
        "partition_strategy": partition_strategy,
        "parallel": parallel,
        "explain": explain,
    }
    auth_map = resolve_auth(auth, principal=principal, tenant=t.tenant)
    try:
        result = await run_in_thread(
            binding.service.query,
            t,
            params=params,
            auth=auth_map,
            request_id=request_id,
        )
        payload = json_safe_result(result)
        if payload.get("status") == "success" and isinstance(payload.get("result"), dict):
            payload["result"]["partition_hints"] = {
                "num_partitions": num_partitions,
                "partition_strategy": partition_strategy,
                "parallel": parallel,
                "explain": explain,
            }
        return payload
    except Exception as exc:
        logger.exception("graph_distributed_execute failed")
        return error_envelope(
            op, str(exc), code="QUERY_EXECUTION", target=t, request_id=request_id
        )
