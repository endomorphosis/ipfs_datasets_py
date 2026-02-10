"""MCP wrapper for knowledge graph querying.

Development pattern:
- Core functionality lives in importable `ipfs_datasets_py` package modules.
- MCP tools are thin wrappers that validate args and delegate.

Core implementation: `ipfs_datasets_py.knowledge_graphs.query_knowledge_graph`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import anyio

logger = logging.getLogger(__name__)


async def query_knowledge_graph(
    graph_id: Optional[str] = None,
    query: str = "",
    query_type: str = "ir",
    max_results: int = 100,
    include_metadata: bool = True,
    *,
    manifest_cid: Optional[str] = None,
    ir_ops: Optional[List[Dict[str, Any]]] = None,
    budgets: Optional[Dict[str, Any]] = None,
    budget_preset: Optional[str] = None,
    ipfs_backend: Optional[str] = None,
    car_fetch_mode: str = "auto",
) -> Dict[str, Any]:
    """MCP tool wrapper.

    Delegates to `ipfs_datasets_py.knowledge_graphs.query_knowledge_graph.query_knowledge_graph`.
    """

    from ipfs_datasets_py.knowledge_graphs.query_knowledge_graph import query_knowledge_graph as core_query

    def _run_sync():
        return core_query(
            graph_id=graph_id,
            query=query,
            query_type=query_type,
            max_results=max_results,
            include_metadata=include_metadata,
            manifest_cid=manifest_cid,
            ir_ops=ir_ops,
            budgets=budgets,
            budget_preset=budget_preset,
            ipfs_backend=ipfs_backend,
            car_fetch_mode=car_fetch_mode,
        )

    try:
        return await anyio.to_thread.run_sync(_run_sync)
    except Exception:
        logger.exception("Error querying knowledge graph")
        raise
