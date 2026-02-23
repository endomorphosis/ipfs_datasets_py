"""
MCP tool for GraphQL query execution against a knowledge graph.

Thin wrapper around KnowledgeGraphManager.graphql_query().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_graphql_query(
    query: str,
    kg_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a GraphQL query against a knowledge graph.

    Parses and executes a GraphQL-style query against the in-memory
    knowledge graph using ``KnowledgeGraphQLExecutor``.

    **Supported GraphQL features:**

    - Top-level field = entity type selector (e.g. ``person { ... }``)
    - Argument filters: ``name``, ``id``, or any entity property
    - Field projection: ``id``, ``type``, ``name``, ``confidence``,
      or any property key
    - Nested field = relationship type traversal
    - Aliases: ``myAlias: fieldName { ... }``

    Args:
        query: GraphQL query string.  For example::

            {
              person(name: "Alice") {
                id
                name
                knows { id name }
              }
            }

        kg_data: Optional serialised knowledge-graph dict (from
            ``kg.to_dict()``).  When ``None`` an empty graph is used.

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``data``: GraphQL ``data`` object (entity type → list of result
          objects, or error list per GraphQL-over-HTTP spec)
        - ``entity_count``: number of entities in the source graph
        - ``query_length``: character length of the submitted query
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.graphql_query(query=query, kg_data=kg_data)
        return result
    except Exception as e:
        logger.error("Error in graph_graphql_query MCP tool: %s", e)
        return {"status": "error", "message": str(e), "query_length": len(query)}
