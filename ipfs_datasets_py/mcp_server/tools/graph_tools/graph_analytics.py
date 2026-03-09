"""
MCP tool for comprehensive knowledge-graph analytics.

Thin wrapper around KnowledgeGraphManager.analytics().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_analytics(
    kg_data: Optional[Dict[str, Any]] = None,
    include_completion_analysis: bool = True,
    include_quality_metrics: bool = True,
    include_topology: bool = True,
    max_completion_suggestions: int = 20,
) -> Dict[str, Any]:
    """
    Compute comprehensive analytics for a knowledge graph.

    Aggregates multiple analysis passes into a single report:

    **Quality metrics** (from :func:`~extraction.extractor.KnowledgeGraphExtractor.compute_extraction_quality_metrics`):
    entity count, relationship count, relationship density, average
    entity/relationship confidence, confidence std-dev, low-confidence ratio,
    entity-type diversity, relationship-type diversity, isolated-entity ratio.

    **KG completion analysis** (from :class:`~query.completion.KnowledgeGraphCompleter`):
    top missing-relationship suggestions (sorted by score), isolated entity IDs,
    and a graph-level completeness indicator.

    **Topology** (pure graph computation):
    entity-type distribution, relationship-type distribution, degree statistics
    (min/max/avg), number of entities with in-degree=0, number with out-degree=0.

    Args:
        kg_data: Optional serialised knowledge-graph dict (from ``kg.to_dict()``).
            When ``None`` an empty in-memory graph is used.
        include_completion_analysis: When ``True`` (default), run KG completion
            pattern analysis and return ``missing_relationships`` +
            ``isolated_entities`` + ``has_completion_suggestions``.
        include_quality_metrics: When ``True`` (default), compute and return
            ``quality_metrics`` (confidence, density, diversity, etc.).
        include_topology: When ``True`` (default), compute and return
            ``topology`` (degree stats, type distributions).
        max_completion_suggestions: Maximum number of missing-relationship
            suggestions to return.  Default 20.

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``entity_count``: total entities
        - ``relationship_count``: total relationships
        - ``quality_metrics``: quality-metrics dict (only when
          *include_quality_metrics* is ``True``)
        - ``missing_relationships``: list of ``{"source_id", "target_id",
          "rel_type", "score", "reason"}`` dicts (only when
          *include_completion_analysis* is ``True``)
        - ``isolated_entities``: list of entity IDs with no relationships
          (only when *include_completion_analysis* is ``True``)
        - ``has_completion_suggestions``: ``True`` when the graph has at least
          one missing-relationship suggestion
        - ``topology``: topology dict with ``entity_type_distribution``,
          ``relationship_type_distribution``, ``degree_stats``
          (only when *include_topology* is ``True``)
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.analytics(
            kg_data=kg_data,
            include_completion_analysis=include_completion_analysis,
            include_quality_metrics=include_quality_metrics,
            include_topology=include_topology,
            max_completion_suggestions=max_completion_suggestions,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_analytics MCP tool: %s", e)
        return {
            "status": "error",
            "message": str(e),
            "entity_count": 0,
            "relationship_count": 0,
        }
