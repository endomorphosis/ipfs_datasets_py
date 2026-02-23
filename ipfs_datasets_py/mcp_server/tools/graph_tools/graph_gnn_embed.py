"""
MCP tool for computing GNN node embeddings from a knowledge graph.

Thin wrapper around KnowledgeGraphManager.gnn_embed().
Core implementation: ipfs_datasets_py.core_operations.knowledge_graph_manager
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from ipfs_datasets_py.core_operations import KnowledgeGraphManager


async def graph_gnn_embed(
    kg_data: Optional[Dict[str, Any]] = None,
    entity_ids: Optional[List[str]] = None,
    top_k_similar: int = 5,
    layer_type: str = "graph_sage",
    embedding_dim: int = 64,
    num_layers: int = 2,
) -> Dict[str, Any]:
    """
    Compute Graph Neural Network (GNN) node embeddings for a knowledge graph.

    Uses the pure-Python ``GraphNeuralNetworkAdapter`` (no PyTorch / TensorFlow
    required) to run message-passing on the graph and produce per-entity
    embedding vectors.  Optionally returns the top-*k* most similar entities
    for each requested entity.

    **Supported layer types:**

    - ``"graph_conv"`` — simple graph convolution (sum aggregation + self-loop)
    - ``"graph_sage"`` — GraphSAGE mean aggregation *(default)*
    - ``"graph_attention"`` — single-head simplified attention

    Args:
        kg_data: Optional serialised knowledge-graph dict (from ``kg.to_dict()``).
            When ``None`` an empty in-memory graph is used and the result will
            contain zero embeddings.
        entity_ids: Optional list of entity IDs for which to return embeddings
            and top-*k* similar entities.  When ``None``, all entities are
            included.
        top_k_similar: Number of most-similar entities to return per entity
            (default 5).  Only computed when *entity_ids* is given.
        layer_type: Message-passing layer type; one of ``"graph_conv"``,
            ``"graph_sage"``, or ``"graph_attention"``.  Default
            ``"graph_sage"``.
        embedding_dim: Target embedding dimensionality (default 64).
        num_layers: Number of message-passing iterations (default 2).

    Returns:
        Dict containing:

        - ``status``: ``"success"`` or ``"error"``
        - ``entity_count``: total number of entities in the graph
        - ``embedding_dim``: actual embedding dimension used
        - ``layer_type``: layer type used
        - ``embeddings``: mapping of ``entity_id → [float, ...]`` (all entities)
        - ``similar``: mapping of ``entity_id → [{"entity_id": str,
          "score": float}]`` (only when *entity_ids* supplied)
    """
    try:
        manager = KnowledgeGraphManager()
        result = await manager.gnn_embed(
            kg_data=kg_data,
            entity_ids=entity_ids,
            top_k_similar=top_k_similar,
            layer_type=layer_type,
            embedding_dim=embedding_dim,
            num_layers=num_layers,
        )
        return result
    except Exception as e:
        logger.error("Error in graph_gnn_embed MCP tool: %s", e)
        return {
            "status": "error",
            "message": str(e),
            "entity_count": 0,
            "embeddings": {},
            "similar": {},
        }
