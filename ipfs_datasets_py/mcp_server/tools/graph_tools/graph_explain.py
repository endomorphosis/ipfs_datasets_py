"""
MCP tool for explainable-AI explanations over a knowledge graph.

Thin wrapper around KnowledgeGraphManager.explain_entity() and
KnowledgeGraphManager.explain_path().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_explain(
    explain_type: str = "entity",
    entity_id: Optional[str] = None,
    start_entity_id: Optional[str] = None,
    end_entity_id: Optional[str] = None,
    relationship_id: Optional[str] = None,
    depth: str = "standard",
    max_hops: int = 4,
    kg_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Produce a structured, human-readable explanation for a KG element.

    Uses ``QueryExplainer`` from ``query/explanation.py`` to explain entities,
    relationships, or shortest paths.

    **Explanation types** (``explain_type`` parameter):

    - ``"entity"`` — Explain a single entity (type, confidence, degree,
      top neighbours, narrative).  Requires *entity_id*.
    - ``"relationship"`` — Explain a single relationship (source/target names,
      symmetry note, context chains).  Requires *relationship_id*.
    - ``"path"`` — Explain the shortest BFS path between two entities
      (hops, cumulative confidence, step-by-step narrative).  Requires
      *start_entity_id* and *end_entity_id*.
    - ``"why_connected"`` — Natural-language connectivity explanation.
      Requires *start_entity_id* and *end_entity_id*.

    **Depth** (``depth`` parameter):

    - ``"surface"`` — minimal, fast
    - ``"standard"`` — default; includes symmetry notes and clusters
    - ``"deep"`` — full; includes alternative paths and cluster hints

    Args:
        explain_type: One of ``"entity"``, ``"relationship"``, ``"path"``,
            ``"why_connected"``.  Default ``"entity"``.
        entity_id: Entity to explain (required for ``"entity"`` type).
        start_entity_id: Source entity ID (required for ``"path"`` /
            ``"why_connected"``).
        end_entity_id: Target entity ID (required for ``"path"`` /
            ``"why_connected"``).
        relationship_id: Relationship to explain (required for
            ``"relationship"`` type).
        depth: Verbosity level — ``"surface"``, ``"standard"``, or
            ``"deep"``.  Default ``"standard"``.
        max_hops: Maximum BFS depth for path explanations.  Default ``4``.
        kg_data: Optional serialised knowledge-graph dict.

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``explain_type``: echoed explain_type value
        - ``explanation``: explanation dict (fields vary by type)
        - ``narrative``: human-readable summary string
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.explain_entity(
            explain_type=explain_type,
            entity_id=entity_id,
            start_entity_id=start_entity_id,
            end_entity_id=end_entity_id,
            relationship_id=relationship_id,
            depth=depth,
            max_hops=max_hops,
            kg_data=kg_data,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_explain MCP tool: %s", e)
        return {"status": "error", "message": str(e), "explain_type": explain_type}
