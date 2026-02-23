"""
Graph Neural Network adapter for KnowledgeGraph.

Provides a pure-Python (no PyTorch / TensorFlow required) implementation of
common GNN primitives:

- Node feature extraction (entity-type one-hot, confidence, in/out degree)
- Message-passing / neighbourhood aggregation (configurable iterations)
- Simple normalisation (unit-length vectors)
- Cosine-similarity link prediction and similar-entity ranking
- Export helpers for interoperability with real GNN frameworks (numpy arrays,
  adjacency dict)

The adapter can be used standalone for lightweight similarity tasks or as a
pre-processing bridge that exports feature matrices to PyTorch Geometric,
DGL, or any other GNN framework.

Example::

    from ipfs_datasets_py.knowledge_graphs.query.gnn import (
        GraphNeuralNetworkAdapter, GNNConfig, GNNLayerType,
    )
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

    kg = KnowledgeGraph("demo")
    alice = kg.add_entity("person", "Alice", confidence=0.9)
    bob   = kg.add_entity("person", "Bob",   confidence=0.8)
    carol = kg.add_entity("org",    "ACME",  confidence=1.0)
    kg.add_relationship("works_at", alice, carol)
    kg.add_relationship("knows",    alice, bob)

    adapter = GraphNeuralNetworkAdapter(kg)
    embeddings = adapter.compute_embeddings()
    print(adapter.link_prediction_score(alice, bob))
    similar = adapter.find_similar_entities(alice, top_k=2)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class GNNLayerType(str, Enum):
    """Supported GNN message-passing layer types."""
    GRAPH_CONV = "graph_conv"       # Simple graph convolution (sum + self-loop)
    GRAPH_SAGE = "graph_sage"       # GraphSAGE mean aggregation
    GRAPH_ATTENTION = "graph_attention"  # Single-head attention (simplified)


@dataclass
class GNNConfig:
    """Configuration for the GNN adapter.

    Attributes:
        embedding_dim: Target dimensionality after message passing.
        num_layers: Number of message-passing iterations.
        layer_type: Which aggregation strategy to use.
        normalize: Whether to L2-normalise output embeddings.
        activation: Element-wise non-linearity ('relu', 'tanh', or 'none').
    """
    embedding_dim: int = 64
    num_layers: int = 2
    layer_type: GNNLayerType = GNNLayerType.GRAPH_SAGE
    normalize: bool = True
    activation: str = "relu"  # 'relu' | 'tanh' | 'none'


@dataclass
class NodeEmbedding:
    """A computed node embedding.

    Attributes:
        entity_id: The ID of the entity this embedding represents.
        features: The embedding vector.
        layer: Which message-passing layer produced this embedding (0 = raw).
    """
    entity_id: str
    features: List[float]
    layer: int = 0

    @property
    def dim(self) -> int:
        """Dimensionality of the embedding vector."""
        return len(self.features)


def _relu(x: float) -> float:
    return max(0.0, x)


def _tanh(x: float) -> float:
    return math.tanh(x)


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Return cosine similarity ∈ [-1, 1]; returns 0.0 for zero vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(ai * bi for ai, bi in zip(a, b))
    norm_a = math.sqrt(sum(ai * ai for ai in a))
    norm_b = math.sqrt(sum(bi * bi for bi in b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.0
    return dot / (norm_a * norm_b)


def _l2_normalize(v: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in v))
    if norm < 1e-12:
        return v[:]
    return [x / norm for x in v]


class GraphNeuralNetworkAdapter:
    """Pure-Python GNN adapter for a :class:`~extraction.graph.KnowledgeGraph`.

    This adapter implements the core operations of a graph neural network
    **without** requiring PyTorch, TensorFlow, or any other ML framework.
    It is suitable for:

    * Lightweight entity similarity ranking inside the knowledge graph.
    * Link-prediction scoring between any two entities.
    * Exporting feature matrices and adjacency dicts to real GNN frameworks.

    Args:
        kg: The :class:`KnowledgeGraph` to operate on.
        config: Hyper-parameters for the GNN computation.
    """

    def __init__(self, kg: Any, config: Optional[GNNConfig] = None) -> None:
        self.kg = kg
        self.config = config or GNNConfig()
        self._embeddings: Optional[Dict[str, NodeEmbedding]] = None

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def extract_node_features(self) -> Dict[str, List[float]]:
        """Extract raw per-node feature vectors.

        Features (in order):
        * One-hot encoding over entity types (alphabetically sorted)
        * Confidence score
        * In-degree (normalised by total number of entities)
        * Out-degree (normalised by total number of entities)

        Returns:
            Mapping of entity_id → feature vector.
        """
        entities = self.kg.entities
        if not entities:
            return {}

        # Build entity-type index
        entity_types = sorted({e.entity_type for e in entities.values()})
        type_index = {t: i for i, t in enumerate(entity_types)}
        n_types = max(len(entity_types), 1)
        n_entities = max(len(entities), 1)

        # Compute degree for each entity
        in_degree: Dict[str, int] = {eid: 0 for eid in entities}
        out_degree: Dict[str, int] = {eid: 0 for eid in entities}
        for rel in self.kg.relationships.values():
            if rel.source_id in out_degree:
                out_degree[rel.source_id] += 1
            if rel.target_id in in_degree:
                in_degree[rel.target_id] += 1

        features: Dict[str, List[float]] = {}
        for eid, entity in entities.items():
            one_hot = [0.0] * n_types
            one_hot[type_index[entity.entity_type]] = 1.0
            confidence = float(getattr(entity, "confidence", 1.0))
            feat = one_hot + [
                confidence,
                in_degree[eid] / n_entities,
                out_degree[eid] / n_entities,
            ]
            features[eid] = feat
        return features

    # ------------------------------------------------------------------
    # Message passing
    # ------------------------------------------------------------------

    def message_passing(
        self,
        features: Dict[str, List[float]],
        num_iterations: Optional[int] = None,
    ) -> Dict[str, List[float]]:
        """Run neighbourhood aggregation for the given number of iterations.

        Aggregation strategy is determined by :attr:`config.layer_type`:

        * ``GRAPH_CONV``: self-feature + sum(neighbour features)
        * ``GRAPH_SAGE``: concat(self, mean(neighbours)) – truncated to input dim
        * ``GRAPH_ATTENTION``: uniform-attention mean aggregation

        Args:
            features: Mapping of entity_id → feature vector.
            num_iterations: Override for :attr:`config.num_layers`.

        Returns:
            Updated mapping of entity_id → aggregated feature vector.
        """
        if not features:
            return {}

        iters = num_iterations if num_iterations is not None else self.config.num_layers
        layer_type = self.config.layer_type
        activate = {
            "relu": _relu,
            "tanh": _tanh,
            "none": lambda x: x,
        }.get(self.config.activation, _relu)

        # Build adjacency (undirected: treat both source and target as neighbours)
        adjacency: Dict[str, List[str]] = {eid: [] for eid in features}
        for rel in self.kg.relationships.values():
            if rel.source_id in adjacency and rel.target_id in adjacency:
                adjacency[rel.source_id].append(rel.target_id)
                adjacency[rel.target_id].append(rel.source_id)

        current = {eid: vec[:] for eid, vec in features.items()}
        dim = len(next(iter(features.values())))

        for _ in range(iters):
            updated: Dict[str, List[float]] = {}
            for eid, self_feat in current.items():
                nbrs = [current[n] for n in adjacency[eid] if n in current]
                if not nbrs:
                    updated[eid] = [activate(x) for x in self_feat]
                    continue

                if layer_type == GNNLayerType.GRAPH_CONV:
                    # self + sum(neighbours)
                    agg = self_feat[:]
                    for nf in nbrs:
                        agg = [a + b for a, b in zip(agg, nf)]
                    updated[eid] = [activate(x) for x in agg]

                elif layer_type == GNNLayerType.GRAPH_SAGE:
                    # mean of neighbours
                    mean_nbr = [
                        sum(nf[i] for nf in nbrs) / len(nbrs)
                        for i in range(dim)
                    ]
                    # concatenate self + mean, then truncate to dim
                    concat = self_feat + mean_nbr
                    updated[eid] = [activate(x) for x in concat[:dim]]

                else:  # GRAPH_ATTENTION — uniform attention
                    n = len(nbrs)
                    mean_nbr = [
                        sum(nf[i] for nf in nbrs) / n
                        for i in range(dim)
                    ]
                    agg = [(s + m) / 2.0 for s, m in zip(self_feat, mean_nbr)]
                    updated[eid] = [activate(x) for x in agg]

            current = updated

        return current

    # ------------------------------------------------------------------
    # Full forward pass
    # ------------------------------------------------------------------

    def compute_embeddings(
        self, force_recompute: bool = False
    ) -> Dict[str, NodeEmbedding]:
        """Compute node embeddings via feature extraction → message passing → optional normalisation.

        Results are cached; pass ``force_recompute=True`` to invalidate.

        Returns:
            Mapping of entity_id → :class:`NodeEmbedding`.
        """
        if self._embeddings is not None and not force_recompute:
            return self._embeddings

        raw = self.extract_node_features()
        aggregated = self.message_passing(raw)

        result: Dict[str, NodeEmbedding] = {}
        for eid, vec in aggregated.items():
            final = _l2_normalize(vec) if self.config.normalize else vec
            result[eid] = NodeEmbedding(
                entity_id=eid,
                features=final,
                layer=self.config.num_layers,
            )
        self._embeddings = result
        return result

    # ------------------------------------------------------------------
    # Similarity and link prediction
    # ------------------------------------------------------------------

    def link_prediction_score(self, entity_a_id: str, entity_b_id: str) -> float:
        """Return a link-prediction score (cosine similarity of embeddings).

        Args:
            entity_a_id: ID of the first entity.
            entity_b_id: ID of the second entity.

        Returns:
            Score ∈ [-1, 1]; 0.0 if either entity is not in the graph.
        """
        embeddings = self.compute_embeddings()
        if entity_a_id not in embeddings or entity_b_id not in embeddings:
            return 0.0
        return _cosine_similarity(
            embeddings[entity_a_id].features,
            embeddings[entity_b_id].features,
        )

    def find_similar_entities(
        self, entity_id: str, top_k: int = 5
    ) -> List[Tuple[str, float]]:
        """Return the top-k most similar entities ranked by cosine similarity.

        Args:
            entity_id: The query entity.
            top_k: Maximum number of results.

        Returns:
            List of ``(other_entity_id, score)`` sorted descending by score;
            excludes the query entity itself.
        """
        embeddings = self.compute_embeddings()
        if entity_id not in embeddings:
            return []
        query_vec = embeddings[entity_id].features
        scores: List[Tuple[str, float]] = []
        for eid, emb in embeddings.items():
            if eid == entity_id:
                continue
            scores.append((eid, _cosine_similarity(query_vec, emb.features)))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------

    def to_adjacency_dict(self) -> Dict[str, List[str]]:
        """Export graph topology as an adjacency dictionary.

        Keys are entity IDs; values are lists of neighbour entity IDs (directed,
        following relationship direction).

        Returns:
            Dict suitable for passing to external GNN frameworks.
        """
        adj: Dict[str, List[str]] = {eid: [] for eid in self.kg.entities}
        for rel in self.kg.relationships.values():
            if rel.source_id in adj:
                adj[rel.source_id].append(rel.target_id)
        return adj

    def export_node_features_array(
        self,
    ) -> Tuple[List[str], List[List[float]]]:
        """Export raw node features as a 2-D feature matrix.

        Returns:
            A tuple ``(entity_ids, feature_matrix)`` where ``feature_matrix[i]``
            is the feature vector for ``entity_ids[i]``.  The ordering is
            deterministic (sorted by entity_id).  Suitable for direct use with
            NumPy / PyTorch / JAX after wrapping with the appropriate array
            constructor.
        """
        features = self.extract_node_features()
        entity_ids = sorted(features.keys())
        matrix = [features[eid] for eid in entity_ids]
        return entity_ids, matrix
