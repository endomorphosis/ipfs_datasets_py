"""
MCP tool for GNN-based link prediction between two knowledge-graph entities.

Thin wrapper around KnowledgeGraphManager.link_predict().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_link_predict(
    entity_a_id: str,
    entity_b_id: str,
    kg_data: Optional[Dict[str, Any]] = None,
    layer_type: str = "graph_sage",
    embedding_dim: int = 64,
    num_layers: int = 2,
    top_candidates: Optional[List[str]] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """
    Compute a GNN-based link-prediction score between two knowledge-graph entities.

    Uses :class:`~query.gnn.GraphNeuralNetworkAdapter` to generate node embeddings
    via graph message-passing, then measures the cosine similarity of the two
    entity embedding vectors as a link-prediction score.

    A score near **1.0** means the two entities are highly similar in graph
    context (i.e. they connect to the same neighbours, share types, etc.) and
    a link between them is strongly predicted.  A score near **0.0** means the
    entities occupy very different graph neighbourhoods and a link is unlikely.

    Optionally, instead of scoring a single pair you can request the top-*k*
    predicted link partners for *entity_a_id* from a list of *top_candidates*.

    Args:
        entity_a_id: ID of the first entity.
        entity_b_id: ID of the second entity (used for the pair score).
        kg_data: Optional serialised knowledge-graph dict.  When ``None``,
            an empty in-memory graph is used and the result will have
            ``score=0.0``.
        layer_type: GNN message-passing layer type; one of ``"graph_conv"``,
            ``"graph_sage"`` *(default)*, ``"graph_attention"``.
        embedding_dim: Embedding dimensionality (default 64).
        num_layers: Number of message-passing iterations (default 2).
        top_candidates: Optional list of entity IDs to rank against
            *entity_a_id*.  When provided, the tool also returns
            ``top_predictions`` — the top-*k* candidates sorted by
            link-prediction score.
        top_k: Maximum number of ranked predictions to return when
            *top_candidates* is given (default 5).

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``entity_a_id``: first entity ID
        - ``entity_b_id``: second entity ID
        - ``score``: cosine-similarity link-prediction score ∈ [-1, 1]
        - ``prediction``: ``"likely"`` when score ≥ 0.5, ``"unlikely"``
          otherwise
        - ``top_predictions``: list of ``{"entity_id": str, "score": float}``
          (only when *top_candidates* supplied)
        - ``layer_type``: the GNN layer type used
        - ``embedding_dim``: the embedding dimension used
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.link_predict(
            entity_a_id=entity_a_id,
            entity_b_id=entity_b_id,
            kg_data=kg_data,
            layer_type=layer_type,
            embedding_dim=embedding_dim,
            num_layers=num_layers,
            top_candidates=top_candidates,
            top_k=top_k,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_link_predict MCP tool: %s", e)
        return {
            "status": "error",
            "message": str(e),
            "entity_a_id": entity_a_id,
            "entity_b_id": entity_b_id,
            "score": 0.0,
            "prediction": "unknown",
        }
