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

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from ..exceptions import KnowledgeGraphError, QueryExecutionError

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
        cache_size: int = 1000
    ):
        self.backend = backend
        self.vector_store = vector_store
        self.default_vector_weight = default_vector_weight
        self.default_graph_weight = default_graph_weight
        self._cache: Dict[str, List[HybridSearchResult]] = {}
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
        except asyncio.CancelledError:
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
        max_nodes: int = 1000
    ) -> Dict[str, int]:
        """
        Expand from seed nodes via graph traversal.
        
        Args:
            seed_nodes: Initial node IDs to expand from
            max_hops: Maximum number of hops to traverse
            rel_types: Optional relationship types to follow
            max_nodes: Maximum number of nodes to return
            
        Returns:
            Dictionary mapping node IDs to hop distance
        """
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
        k: int = 10
    ) -> List[HybridSearchResult]:
        """
        Fuse vector and graph results using reciprocal rank fusion.
        
        Args:
            vector_results: Results from vector search
            graph_nodes: Node IDs with hop distances from graph expansion
            vector_weight: Weight for vector scores
            graph_weight: Weight for graph scores
            k: Number of final results to return
            
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
            graph_score = 1.0 - (hop_distance / (max_hop + 1))
            
            if node_id in all_nodes:
                # Update existing result
                result = all_nodes[node_id]
                result.graph_score = graph_score
                result.hop_distance = hop_distance
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
                    hop_distance=hop_distance
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
        enable_cache: bool = True
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
            
        Returns:
            List of hybrid search results
        """
        # Use default weights if not provided
        vector_weight = vector_weight if vector_weight is not None else self.default_vector_weight
        graph_weight = graph_weight if graph_weight is not None else self.default_graph_weight
        
        # Check cache
        cache_key = f"{query}:{k}:{vector_weight}:{graph_weight}:{max_hops}"
        if enable_cache and cache_key in self._cache:
            logger.debug(f"Cache hit for query: {query[:50]}")
            return self._cache[cache_key]
        
        # Step 1: Vector search
        logger.debug(f"Performing vector search for: {query[:50]}")
        vector_results = self.vector_search(query, k=k * 2, embeddings=embeddings)
        
        if not vector_results:
            logger.warning("No vector results found")
            return []
        
        # Step 2: Graph expansion
        logger.debug(f"Expanding graph from {len(vector_results)} seed nodes")
        seed_nodes = [r.node_id for r in vector_results]
        graph_nodes = self.expand_graph(seed_nodes, max_hops=max_hops)
        
        # Step 3: Fuse results
        logger.debug(f"Fusing {len(vector_results)} vector results with {len(graph_nodes)} graph nodes")
        fused_results = self.fuse_results(
            vector_results,
            graph_nodes,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            k=k
        )
        
        # Cache results
        if enable_cache:
            self._cache[cache_key] = fused_results
            # Simple cache eviction
            if len(self._cache) > self._cache_size:
                # Remove oldest entry
                self._cache.pop(next(iter(self._cache)))
        
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
        except asyncio.CancelledError:
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
        except asyncio.CancelledError:
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
        logger.debug("Cache cleared")


__all__ = ['HybridSearchEngine', 'HybridSearchResult']
