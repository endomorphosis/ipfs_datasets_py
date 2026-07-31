"""MCP tool: SRL extraction bound to an explicit GraphTarget."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Union

from ._bridge import (
    ABILITY_WRITE,
    DEFAULT_BRANCH,
    EFFECT_WRITE,
    declare_mcp_plus,
    error_envelope,
    resolve_target,
    wrap_specialized_result,
)

logger = logging.getLogger(__name__)


@declare_mcp_plus(
    ability=ABILITY_WRITE,
    effects=[EFFECT_WRITE],
    resource_template="kg://{tenant}/{graph_id}",
    mutates=True,
)
async def graph_srl_extract(
    text: Optional[str] = None,
    target: Optional[Union[str, Mapping[str, Any]]] = None,
    *,
    tenant: Optional[str] = None,
    graph_id: Optional[str] = None,
    graph: Optional[str] = None,
    branch: Optional[str] = None,
    backend: str = "heuristic",
    return_triples: bool = False,
    return_temporal_graph: bool = False,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract SRL frames; requires an explicit graph target for attribution."""
    op = "write"
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
    if not text:
        return error_envelope(
            op, "text is required", code="INVALID_REQUEST", target=t
        )

    try:
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager

        manager = KnowledgeGraphManager()
        result = await manager.extract_srl(
            text=text,
            backend=backend,
            return_triples=return_triples,
            return_temporal_graph=return_temporal_graph,
        )
        if not isinstance(result, dict):
            result = {"status": "success", "result": result}
        return wrap_specialized_result(op, target=t, payload=result, request_id=request_id)
    except Exception as exc:
        logger.exception("graph_srl_extract failed")
        return error_envelope(op, str(exc), code="INTERNAL", target=t, request_id=request_id)
