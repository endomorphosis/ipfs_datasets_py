"""
MCP tool for querying across federated knowledge graphs.

Thin wrapper around KnowledgeGraphManager.federate_query().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_federate_query(
    graphs: Optional[List[Dict[str, Any]]] = None,
    query_entity_name: Optional[str] = None,
    query_entity_type: Optional[str] = None,
    resolution_strategy: str = "type_and_name",
    merge: bool = False,
    max_results: int = 50,
) -> Dict[str, Any]:
    """
    Query across a federation of independent knowledge graphs.

    Uses :class:`~ipfs_datasets_py.knowledge_graphs.query.federation.FederatedKnowledgeGraph`
    to perform cross-graph entity resolution and unified query execution across
    multiple independent knowledge graphs.

    **Entity resolution strategies:**

    - ``"type_and_name"`` *(default)* — entities match when both
      ``(entity_type.lower(), name.lower())`` are equal.  Prevents
      "person:Alice" from merging with "company:Alice".
    - ``"exact_name"`` — match on ``name`` only (case-insensitive).
    - ``"property_match"`` — additionally requires at least one matching
      property key/value pair.

    **Two query modes:**

    1. **Entity lookup** (set *query_entity_name* and optionally
       *query_entity_type*) — search for an entity across all graphs.
    2. **Merge** (*merge=True*) — merge all supplied graphs into a single
       deduplicated :class:`~extraction.graph.KnowledgeGraph`.

    Args:
        graphs: Optional list of serialised knowledge-graph dicts
            (each from ``kg.to_dict()``).  When ``None`` or empty, an empty
            result is returned.
        query_entity_name: Name of the entity to search for across all
            graphs.  When ``None``, entity-lookup mode is skipped.
        query_entity_type: Optional type filter for entity lookup.
        resolution_strategy: Cross-graph entity resolution strategy; one of
            ``"type_and_name"`` *(default)*, ``"exact_name"``, or
            ``"property_match"``.
        merge: When ``True``, merge all graphs into one and return the merged
            graph entity/relationship counts.  Default ``False``.
        max_results: Maximum number of entity-lookup results returned.
            Default 50.

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``graph_count``: number of input graphs
        - ``resolution_strategy``: strategy used
        - ``entity_matches``: list of cross-graph entity match dicts (each
          with ``entity_a_id``, ``entity_b_id``, ``kg_a_index``,
          ``kg_b_index``, ``score``, ``strategy``) — only when *graphs* given
        - ``query_hits``: list of ``{"graph_index": int, "entity_id": str,
          "entity_type": str, "name": str}`` — only when *query_entity_name*
          given
        - ``merged_entity_count``: entity count after merge (only when
          *merge=True*)
        - ``merged_relationship_count``: relationship count after merge (only
          when *merge=True*)
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.federate_query(
            graphs=graphs,
            query_entity_name=query_entity_name,
            query_entity_type=query_entity_type,
            resolution_strategy=resolution_strategy,
            merge=merge,
            max_results=max_results,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_federate_query MCP tool: %s", e)
        return {
            "status": "error",
            "message": str(e),
            "graph_count": len(graphs) if graphs else 0,
            "entity_matches": [],
            "query_hits": [],
        }
