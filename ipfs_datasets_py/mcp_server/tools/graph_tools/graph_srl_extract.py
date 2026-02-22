"""
MCP tool for Semantic Role Labeling (SRL) extraction from text.

Thin wrapper around KnowledgeGraphManager.extract_srl().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_srl_extract(
    text: str,
    backend: str = "heuristic",
    return_triples: bool = False,
    return_temporal_graph: bool = False,
) -> Dict[str, Any]:
    """
    Extract Semantic Role Labeling (SRL) frames from text.

    Identifies predicate–argument structure (who did what to whom, where, when)
    and returns a list of SRL frames, optionally as (subject, predicate, object)
    triples or an event-centric temporal graph.

    Args:
        text: The input text to analyze.
        backend: ``"heuristic"`` (default, no dependencies) or ``"spacy"``
            (requires a loaded spaCy model).
        return_triples: If ``True``, also return the frames as flat
            ``(subject, predicate, object)`` triple tuples.
        return_temporal_graph: If ``True``, also return an event-centric
            temporal ordering graph (PRECEDES/OVERLAPS relationships).

    Returns:
        Dict containing:
        - ``status``: ``"success"`` or ``"error"``
        - ``frame_count``: number of SRL frames extracted
        - ``frames``: list of frame dicts (predicate, roles, confidence)
        - ``triples``: (if *return_triples* is True) list of
          ``[subject, predicate, object]`` lists
        - ``temporal_graph_nodes``: (if *return_temporal_graph* is True)
          count of event nodes in the temporal graph
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.extract_srl(
            text=text,
            backend=backend,
            return_triples=return_triples,
            return_temporal_graph=return_temporal_graph,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_srl_extract MCP tool: %s", e)
        return {"status": "error", "message": str(e), "text_length": len(text)}
