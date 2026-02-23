"""
MCP tool for knowledge graph completion (missing-relationship suggestions).

Thin wrapper around KnowledgeGraphManager.suggest_completions().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_complete_suggestions(
    kg_data: Optional[Dict[str, Any]] = None,
    min_score: float = 0.3,
    max_suggestions: int = 20,
    entity_id: Optional[str] = None,
    rel_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Suggest missing relationships in a knowledge graph.

    Uses ``KnowledgeGraphCompleter`` to detect likely-missing edges using six
    structural graph-analysis patterns (no external ML libraries required):

    - **Triadic closure** — A→B and B→C → suggest A→C
    - **Common neighbour** — entities sharing many neighbours (Jaccard)
    - **Symmetric relation** — A→knows→B → suggest B→knows→A
    - **Transitive relation** — same rel-type chain shortcut
    - **Inverse relation** — A→parent_of→B → suggest B→child_of→A
    - **Type compatibility** — same-type entities sharing common targets

    Args:
        kg_data: Optional serialised knowledge-graph dict.  When ``None``
            an empty in-memory graph is used.
        min_score: Minimum confidence score for a suggestion to be included
            (0.0–1.0).  Default ``0.3``.
        max_suggestions: Maximum number of suggestions to return.  Default
            ``20``.
        entity_id: If provided, only return suggestions involving this entity
            as the source.
        rel_type: If provided, only return suggestions of this relationship
            type.

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``suggestion_count``: total number of suggestions returned
        - ``suggestions``: list of suggestion dicts, each with keys
          ``source_id``, ``target_id``, ``rel_type``, ``score``,
          ``reason``, ``evidence``
        - ``isolated_entity_count``: number of entities with no relationships
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.suggest_completions(
            kg_data=kg_data,
            min_score=min_score,
            max_suggestions=max_suggestions,
            entity_id=entity_id,
            rel_type=rel_type,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_complete_suggestions MCP tool: %s", e)
        return {"status": "error", "message": str(e), "min_score": min_score}
