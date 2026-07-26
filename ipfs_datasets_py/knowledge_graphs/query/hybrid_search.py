"""
Hybrid Search Engine

This module implements hybrid search combining vector similarity search with
knowledge graph traversal. It consolidates hybrid search logic from multiple
fragmented implementations.

The hybrid search approach:
1. Vector Search: Find semantically similar nodes using embeddings
2. Graph Expansion: Expand from seed nodes via graph traversal
3. Result Fusion: Combine and rank results using weighted scoring

Features:
- Multi-model embedding support
- Configurable vector/graph weights
- Reciprocal rank fusion
- Budget-aware execution
- Caching for performance

Usage:
    from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine
    
    engine = HybridSearchEngine(backend=backend, vector_store=vector_store)
    
    results = engine.search(
        query="What is IPFS?",
        k=10,
        vector_weight=0.6,
        graph_weight=0.4,
        max_hops=2
    )
"""

import asyncio as stdlib_asyncio
import anyio
import hashlib
import logging
from typing import Any, Dict, List, Mapping, Optional
from dataclasses import dataclass, replace


def _cancelled_exc_class() -> type:
    """Return the current async framework's cancellation exception class.

    Falls back to stdlib asyncio when called outside an async context.
    """
    try:
        return anyio.get_cancelled_exc_class()
    except anyio.NoEventLoopError:
        return stdlib_asyncio.CancelledError

from ..exceptions import KnowledgeGraphError, QueryExecutionError
from .semantic_traversal import (
    EmbeddingGuidedTraversal,
    GraphNeighborProvider,
    NodeEmbeddingProvider,
    ObjectGraphNeighborProvider,
    ObjectNodeEmbeddingProvider,
    SemanticTraversalConfig,
    SemanticTraversalResult,
)

logger = logging.getLogger(__name__)


@dataclass
class HybridSearchResult:
    """
    Result from hybrid search.
    
    Attributes:
        node_id: Node identifier
        score: Combined score (0-1)
        vector_score: Vector similarity score
        graph_score: Graph relevance score
        hop_distance: Distance from seed nodes
        metadata: Additional metadata
    """
    node_id: str
    score: float
    vector_score: float = 0.0
    graph_score: float = 0.0
    hop_distance: int = 0
    metadata: Optional[Dict[str, Any]] = None
    
    def __repr__(self) -> str:
        return f"HybridSearchResult(node_id={self.node_id}, score={self.score:.3f})"


class HybridSearchEngine:
    """
    Hybrid search engine combining vector similarity and graph traversal.
    
    This engine provides unified hybrid search functionality, consolidating
    implementations from:
    - processors/graphrag/integration.py (HybridVectorGraphSearch)
    - search/graphrag_integration/graphrag_integration.py (HybridVectorGraphSearch)
    
    The hybrid approach leverages both semantic similarity (via embeddings) and
    structural relationships (via graph traversal) for enhanced retrieval.
    
    Args:
        backend: Graph backend for traversal
        vector_store: Optional vector store for similarity search
        default_vector_weight: Default weight for vector scores (0-1)
        default_graph_weight: Default weight for graph scores (0-1)
        cache_size: Size of result cache
    
    Example:
        engine = HybridSearchEngine(backend, vector_store)
        results = engine.search("query text", k=10)
    """
    
    def __init__(
        self,
        backend: Any,
        vector_store: Optional[Any] = None,
        default_vector_weight: float = 0.6,
        default_graph_weight: float = 0.4,
        cache_size: int = 1000,
        neighbor_provider: Optional[GraphNeighborProvider] = None,
        embedding_provider: Optional[NodeEmbeddingProvider] = None,
    ):
        self.backend = backend
        self.vector_store = vector_store
        self.default_vector_weight = default_vector_weight
        self.default_graph_weight = default_graph_weight
        self.neighbor_provider = (
            neighbor_provider or ObjectGraphNeighborProvider(backend)
        )
        self.embedding_provider = (
            embedding_provider or ObjectNodeEmbeddingProvider(vector_store)
        )
        self._last_semantic_traversal: Optional[SemanticTraversalResult] = None
        self._cache: Dict[str, List[HybridSearchResult]] = {}
        self._cache_traversals: Dict[
            str,
            Optional[SemanticTraversalResult],
        ] = {}
        self._cache_size = cache_size
    
    def vector_search(
        self,
        query: str,
        k: int = 10,
        embeddings: Optional[Dict[str, Any]] = None
    ) -> List[HybridSearchResult]:
        """
        Perform vector similarity search.
        
        Args:
            query: Query text
            k: Number of results to return
            embeddings: Optional pre-computed embeddings
            
        Returns:
            List of search results with vector scores
        """
        if self.vector_store is None:
            logger.warning("No vector store available for vector search")
            return []
        
        try:
            # Get embedding for query
            if embeddings and 'query_embedding' in embeddings:
                query_embedding = embeddings['query_embedding']
            else:
                # This would call the vector store's embedding method
                query_embedding = self._get_query_embedding(query)

            if query_embedding is None:
                logger.warning("No query embedding available; vector search skipped")
                return []
            
            # Search vector store
            vector_results = self.vector_store.search(query_embedding, k=k)
            
            # Convert to HybridSearchResult
            results = []
            for node_id, score in vector_results:
                results.append(HybridSearchResult(
                    node_id=node_id,
                    score=score,
                    vector_score=score,
                    graph_score=0.0,
                    hop_distance=0
                ))
            
            return results
            
        except KnowledgeGraphError:
            raise
        except _cancelled_exc_class():
            raise
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.error(f"Vector search failed (degrading gracefully): {e}")
            return []
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            raise QueryExecutionError(
                f"Vector search failed: {e}",
                details={
                    'query': query,
                    'k': k,
                    'error': str(e),
                    'error_class': type(e).__name__,
                }
            ) from e
    
    def expand_graph(
        self,
        seed_nodes: List[str],
        max_hops: int = 2,
        rel_types: Optional[List[str]] = None,
        max_nodes: int = 1000,
        *,
        traversal_strategy: str = "bfs",
        query_embedding: Optional[Any] = None,
        direction: Optional[str] = None,
        semantic_config: Optional[SemanticTraversalConfig] = None,
    ) -> Dict[str, int]:
        """
        Expand from seed nodes via graph traversal.
        
        Args:
            seed_nodes: Initial node IDs to expand from
            max_hops: Maximum number of hops to traverse
            rel_types: Optional relationship types to follow
            max_nodes: Maximum number of nodes to return
            traversal_strategy: ``"bfs"`` (default) or a semantic strategy
                alias such as ``"semantic_beam"``.
            query_embedding: Query vector required by semantic traversal.
            direction: ``incoming``, ``outgoing``, ``both``, or ``adaptive``.
                Adaptive traversal fetches both directions and lets semantic
                scoring choose the useful branch.
            semantic_config: Optional stricter semantic traversal budgets.
            
        Returns:
            Dictionary mapping node IDs to hop distance
        """
        normalized_strategy = traversal_strategy.strip().lower().replace("-", "_")
        bfs_strategies = {"bfs", "breadth_first", "breadth_first_search"}
        semantic_strategies = {
            "semantic",
            "semantic_beam",
            "semantic_best_first",
            "embedding_guided",
        }
        if normalized_strategy in semantic_strategies:
            if query_embedding is None:
                raise ValueError(
                    "query_embedding is required for semantic graph traversal"
                )
            active_config = semantic_config or SemanticTraversalConfig(
                max_depth=max_hops,
                max_nodes=max_nodes,
                direction=direction or "outgoing",
                relationship_types=tuple(rel_types or ()),
            )
            # The legacy method limits remain hard outer bounds.  A supplied
            # semantic config may make them stricter, never unexpectedly wider.
            active_config = replace(
                active_config,
                max_depth=min(active_config.max_depth, max_hops),
                max_nodes=min(active_config.max_nodes, max_nodes),
                direction=direction or active_config.direction,
                relationship_types=(
                    tuple(rel_types)
                    if rel_types is not None
                    else active_config.relationship_types
                ),
            )
            traversal = EmbeddingGuidedTraversal(
                self.neighbor_provider,
                self.embedding_provider,
                active_config,
            )
            self._last_semantic_traversal = traversal.traverse(
                seed_nodes,
                query_embedding,
            )
            return dict(self._last_semantic_traversal.hop_distances)
        if normalized_strategy not in bfs_strategies:
            choices = ", ".join(sorted(bfs_strategies | semantic_strategies))
            raise ValueError(f"unknown traversal_strategy; expected one of: {choices}")

        self._last_semantic_traversal = None
        visited: Dict[str, int] = {}
        current_level = set(seed_nodes)
        
        for hop in range(max_hops + 1):
            if not current_level or len(visited) >= max_nodes:
                break
            
            next_level = set()
            
            for node_id in current_level:
                if node_id in visited:
                    continue
                
                visited[node_id] = hop
                
                # Get neighbors from backend
                try:
                    if direction and direction != "outgoing":
                        edges = self.neighbor_provider.get_neighbors(
                            node_id,
                            direction=direction,
                            relationship_types=tuple(rel_types or ()),
                            limit=max_nodes,
                        )
                        neighbors = [edge.target_id for edge in edges]
                    else:
                        neighbors = self._get_neighbors(node_id, rel_types)
                    for neighbor_id in neighbors:
                        if neighbor_id not in visited and len(visited) < max_nodes:
                            next_level.add(neighbor_id)
                except (KnowledgeGraphError, AttributeError, TypeError, ValueError, KeyError) as e:
                    logger.warning(f"Failed to get neighbors for {node_id} (continuing): {e}")
            
            current_level = next_level
        
        return visited
    
    def fuse_results(
        self,
        vector_results: List[HybridSearchResult],
        graph_nodes: Dict[str, int],
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        k: int = 10,
        semantic_scores: Optional[Mapping[str, float]] = None,
        semantic_metadata: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> List[HybridSearchResult]:
        """
        Fuse vector and graph results using reciprocal rank fusion.
        
        Args:
            vector_results: Results from vector search
            graph_nodes: Node IDs with hop distances from graph expansion
            vector_weight: Weight for vector scores
            graph_weight: Weight for graph scores
            k: Number of final results to return
            semantic_scores: Optional traversal scores used to refine graph
                relevance for embedding-guided expansion.
            semantic_metadata: Optional per-node traversal diagnostics copied
                into result metadata.
            
        Returns:
            Fused and ranked results
        """
        # Normalize weights
        total_weight = vector_weight + graph_weight
        if total_weight > 0:
            vector_weight = vector_weight / total_weight
            graph_weight = graph_weight / total_weight
        
        # Build combined result set
        all_nodes: Dict[str, HybridSearchResult] = {}
        
        # Add vector results
        for result in vector_results:
            all_nodes[result.node_id] = result
        
        # Add/update with graph results
        max_hop = max(graph_nodes.values()) if graph_nodes else 1
        for node_id, hop_distance in graph_nodes.items():
            # Graph score inversely proportional to hop distance
            structural_score = 1.0 - (hop_distance / (max_hop + 1))
            graph_score = structural_score
            if semantic_scores and node_id in semantic_scores:
                raw_semantic_score = semantic_scores[node_id]
                normalized_semantic_score = max(
                    0.0,
                    min(1.0, (raw_semantic_score + 1.0) / 2.0),
                )
                graph_score = (
                    0.5 * structural_score + 0.5 * normalized_semantic_score
                )
            
            if node_id in all_nodes:
                # Update existing result
                result = all_nodes[node_id]
                result.graph_score = graph_score
                result.hop_distance = hop_distance
                if semantic_metadata and node_id in semantic_metadata:
                    result.metadata = {
                        **(result.metadata or {}),
                        "semantic_traversal": dict(semantic_metadata[node_id]),
                    }
                # Recalculate combined score
                result.score = (vector_weight * result.vector_score + 
                               graph_weight * graph_score)
            else:
                # Create new result
                all_nodes[node_id] = HybridSearchResult(
                    node_id=node_id,
                    score=graph_weight * graph_score,
                    vector_score=0.0,
                    graph_score=graph_score,
                    hop_distance=hop_distance,
                    metadata=(
                        {
                            "semantic_traversal": dict(
                                semantic_metadata[node_id]
                            )
                        }
                        if semantic_metadata and node_id in semantic_metadata
                        else None
                    ),
                )
        
        # Sort by combined score and return top k
        sorted_results = sorted(
            all_nodes.values(),
            key=lambda x: x.score,
            reverse=True
        )
        
        return sorted_results[:k]
    
    def search(
        self,
        query: str,
        k: int = 10,
        vector_weight: Optional[float] = None,
        graph_weight: Optional[float] = None,
        max_hops: int = 2,
        embeddings: Optional[Dict[str, Any]] = None,
        enable_cache: bool = True,
        traversal_strategy: str = "bfs",
        direction: Optional[str] = None,
        semantic_config: Optional[SemanticTraversalConfig] = None,
        rel_types: Optional[List[str]] = None,
        max_nodes: int = 1000,
    ) -> List[HybridSearchResult]:
        """
        Perform hybrid search combining vector similarity and graph traversal.
        
        Args:
            query: Query text
            k: Number of results to return
            vector_weight: Weight for vector scores (default: 0.6)
            graph_weight: Weight for graph scores (default: 0.4)
            max_hops: Maximum graph traversal hops
            embeddings: Optional pre-computed embeddings
            enable_cache: Whether to use result caching
            traversal_strategy: ``"bfs"`` or an embedding-guided strategy.
            direction: Optional graph direction for expansion.
            semantic_config: Semantic traversal weights and hard budgets.
            rel_types: Optional relationship-type allowlist.
            max_nodes: Hard graph expansion result limit.
            
        Returns:
            List of hybrid search results
        """
        # Use default weights if not provided
        vector_weight = vector_weight if vector_weight is not None else self.default_vector_weight
        graph_weight = graph_weight if graph_weight is not None else self.default_graph_weight
        
        # Check cache
        config_key = repr(semantic_config) if semantic_config is not None else ""
        supplied_query_embedding = (
            embeddings.get("query_embedding")
            if embeddings and "query_embedding" in embeddings
            else None
        )
        embedding_key = self._embedding_fingerprint(supplied_query_embedding)
        cache_key = (
            f"{query}:{k}:{vector_weight}:{graph_weight}:{max_hops}:"
            f"{traversal_strategy}:{direction}:{tuple(rel_types or ())}:"
            f"{max_nodes}:{config_key}:{embedding_key}"
        )
        if enable_cache and cache_key in self._cache:
            logger.debug(f"Cache hit for query: {query[:50]}")
            self._last_semantic_traversal = self._cache_traversals.get(
                cache_key
            )
            return self._cache[cache_key]
        
        # Step 1: Vector search
        logger.debug(f"Performing vector search for: {query[:50]}")
        query_embedding = (
            embeddings.get("query_embedding")
            if embeddings and "query_embedding" in embeddings
            else self._get_query_embedding(query)
        )
        vector_embeddings = (
            {**(embeddings or {}), "query_embedding": query_embedding}
            if query_embedding is not None
            else embeddings
        )
        vector_results = self.vector_search(
            query,
            k=k * 2,
            embeddings=vector_embeddings,
        )
        
        if not vector_results:
            logger.warning("No vector results found")
            return []
        
        # Step 2: Graph expansion
        logger.debug(f"Expanding graph from {len(vector_results)} seed nodes")
        seed_nodes = [r.node_id for r in vector_results]
        graph_nodes = self.expand_graph(
            seed_nodes,
            max_hops=max_hops,
            rel_types=rel_types,
            max_nodes=max_nodes,
            traversal_strategy=traversal_strategy,
            query_embedding=query_embedding,
            direction=direction,
            semantic_config=semantic_config,
        )

        semantic_scores: Optional[Dict[str, float]] = None
        semantic_metadata: Optional[Dict[str, Mapping[str, Any]]] = None
        if self._last_semantic_traversal is not None:
            semantic_scores = {
                node_id: candidate.score
                for node_id, candidate in (
                    self._last_semantic_traversal.candidates.items()
                )
            }
            semantic_metadata = {
                node_id: candidate.to_dict()
                for node_id, candidate in (
                    self._last_semantic_traversal.candidates.items()
                )
            }
        
        # Step 3: Fuse results
        logger.debug(f"Fusing {len(vector_results)} vector results with {len(graph_nodes)} graph nodes")
        fused_results = self.fuse_results(
            vector_results,
            graph_nodes,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            k=k,
            semantic_scores=semantic_scores,
            semantic_metadata=semantic_metadata,
        )
        
        # Cache results
        if enable_cache:
            self._cache[cache_key] = fused_results
            self._cache_traversals[cache_key] = self._last_semantic_traversal
            # Simple cache eviction
            if len(self._cache) > self._cache_size:
                # Remove oldest entry
                oldest_key = next(iter(self._cache))
                self._cache.pop(oldest_key)
                self._cache_traversals.pop(oldest_key, None)
        
        return fused_results
    
    def _get_query_embedding(self, query: str) -> Any:
        """
        Get embedding for query text.
        
        Args:
            query: Query text to embed
            
        Returns:
            Query embedding vector (or None if unavailable)
        """
        if self.vector_store is None:
            logger.debug("No vector store available for embedding")
            return None
        
        try:
            # Try to get embedding from vector store
            if hasattr(self.vector_store, 'embed_query'):
                return self.vector_store.embed_query(query)
            elif hasattr(self.vector_store, 'get_embedding'):
                return self.vector_store.get_embedding(query)
            else:
                logger.warning("Vector store does not support embedding generation")
                return None
        except KnowledgeGraphError:
            raise
        except _cancelled_exc_class():
            raise
        except (AttributeError, TypeError, ValueError) as e:
            logger.error(f"Failed to generate embedding (degrading gracefully): {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None
    
    def _get_neighbors(self, node_id: str, rel_types: Optional[List[str]] = None) -> List[str]:
        """
        Get neighbors of a node from the graph backend.
        
        Args:
            node_id: Node identifier
            rel_types: Optional relationship types to filter by
            
        Returns:
            List of neighbor node IDs
        """
        try:
            # Try different backend methods
            if hasattr(self.backend, 'get_neighbors'):
                neighbors = self.backend.get_neighbors(node_id, rel_types=rel_types)
                if isinstance(neighbors, list):
                    return neighbors
            
            if hasattr(self.backend, 'get_relationships'):
                # Get all relationships for this node
                rels = self.backend.get_relationships(node_id)
                neighbors = []
                for rel in rels:
                    # Filter by relationship type if specified
                    if rel_types is None or rel.get('type') in rel_types:
                        # Add target node if it's not the source
                        target = rel.get('target') or rel.get('end_node')
                        if target and target != node_id:
                            neighbors.append(target)
                return neighbors
            
            logger.debug(f"Backend does not support neighbor retrieval for node {node_id}")
            return []
            
        except KnowledgeGraphError:
            raise
        except _cancelled_exc_class():
            raise
        except (AttributeError, TypeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to get neighbors for {node_id} (degrading gracefully): {e}")
            return []
        except Exception as e:
            logger.warning(f"Failed to get neighbors for {node_id}: {e}")
            return []
    
    def clear_cache(self) -> None:
        """Clear the result cache."""
        self._cache.clear()
        self._cache_traversals.clear()
        logger.debug("Cache cleared")

    @staticmethod
    def _embedding_fingerprint(embedding: Optional[Any]) -> str:
        """Create a compact cache discriminator for a supplied query vector."""
        if embedding is None:
            return "auto"
        try:
            payload = ",".join(f"{float(value):.12g}" for value in embedding)
        except (TypeError, ValueError, OverflowError):
            payload = repr(embedding)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = ['HybridSearchEngine', 'HybridSearchResult']
