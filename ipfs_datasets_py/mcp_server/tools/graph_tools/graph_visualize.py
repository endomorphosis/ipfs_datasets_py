"""
MCP tool for knowledge graph visualization export.

Thin wrapper around KnowledgeGraphManager.visualize().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_visualize(
    format: str = "dot",
    kg_data: Optional[Dict[str, Any]] = None,
    max_entities: Optional[int] = None,
    directed: bool = True,
    graph_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Export a knowledge graph as a visualization format string.

    Uses ``KnowledgeGraphVisualizer`` (pure-Python, no external deps) to
    produce a text representation that can be rendered by external tools.

    **Supported formats:**

    - ``"dot"`` — Graphviz DOT language; render with ``dot -Tsvg``
    - ``"mermaid"`` — Mermaid.js graph notation; paste into live editor
    - ``"d3_json"`` — D3.js force-directed graph JSON
    - ``"ascii"`` — ASCII tree (human-readable, no tooling needed)

    Args:
        format: Output format; one of ``"dot"``, ``"mermaid"``,
            ``"d3_json"``, or ``"ascii"``.  Default ``"dot"``.
        kg_data: Optional serialised knowledge-graph dict.  When ``None``
            an empty in-memory graph is used.
        max_entities: Optional cap on the number of entities included in
            the output (useful for very large graphs).  Default ``None``
            (include all).
        directed: When ``True`` (default) emit a directed graph (``digraph``
            for DOT, ``graph LR`` direction arrow for Mermaid).  Only
            affects ``"dot"`` and ``"mermaid"`` output.
        graph_name: Optional name override for the Graphviz ``digraph``
            identifier.

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``format``: the format that was produced
        - ``output``: the visualization string (or JSON dict for ``"d3_json"``)
        - ``entity_count``: number of entities in the source graph
        - ``relationship_count``: number of relationships in the source graph
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.visualize(
            format=format,
            kg_data=kg_data,
            max_entities=max_entities,
            directed=directed,
            graph_name=graph_name,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_visualize MCP tool: %s", e)
        return {"status": "error", "message": str(e), "format": format}
