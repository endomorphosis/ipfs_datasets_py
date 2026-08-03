"""MCP tool: ontology materialize — requires explicit GraphTarget."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_ADMIN,
    DEFAULT_BRANCH,
    EFFECT_ADMIN,
    declare_mcp_plus,
    error_envelope,
    load_snapshot_payload,
    resolve_target,
    wrap_specialized_result,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_ADMIN,
    effects=[EFFECT_ADMIN],
    resource_template="kg://{tenant}/{graph_id}",
    mutates=True,
)
async def graph_ontology_materialize(
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    graph_name: Optional[str] = None,
    branch: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    check_consistency: bool = False,
    explain: bool = False,
    catalog_path: Optional[str] = None,
    storage_path: Optional[str] = None,
    auth: Optional[Mapping[str, Any]] = None,
    principal: Optional[str] = None,
    request_id: Optional[str] = None,
    driver_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Materialize ontology inferences for an explicit graph target."""
    op = "write"
    t, err = resolve_target(
        target=target,
        tenant=tenant,
        graph_id=graph_id or graph_name,
        graph=graph or graph_name,
        branch=branch,
        require_graph=True,
        default_branch=DEFAULT_BRANCH,
        operation=op,
    )
    if err is not None:
        return err

    resolved, kg_data, load_err = await load_snapshot_payload(
        target=t.to_json_dict() if t else None,
        catalog_path=catalog_path,
        storage_path=storage_path,
        auth=auth,
        principal=principal,
        request_id=request_id,
        operation="query",
    )
    if load_err is not None and (load_err.get("error") or {}).get("code") not in {
        "NOT_FOUND",
        "INVALID_TARGET",
    }:
        # Proceed with empty kg if graph not yet populated.
        if (load_err.get("error") or {}).get("code") not in {"NOT_FOUND"}:
            pass

    try:
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        manager = KnowledgeGraphManager()
        name = (resolved or t).graph_id if (resolved or t) else (graph_name or "graph")
        result = await manager.ontology_materialize(
            graph_name=name,
            schema=schema,
            check_consistency=check_consistency,
            explain=explain,
        )
        if not isinstance(result, dict):
            result = {"status": "success", "result": result}
        if kg_data:
            result.setdefault("revision", kg_data.get("revision"))
        return wrap_specialized_result(
            op, target=resolved or t, payload=result, request_id=request_id
        )
    except Exception as exc:
        logger.exception("graph_ontology_materialize failed")
        return error_envelope(
            op, str(exc), code="INTERNAL", target=t, request_id=request_id
        )
