"""
Embedding-Enhanced Prover (Phase 3.2)

This module implements embedding-based theorem retrieval and similarity matching
to enhance symbolic proving with neural pattern recognition.

Key features:
- Formula embedding: Convert logic formulas to dense vectors
- Similarity search: Find similar theorems/axioms using cosine similarity
- Semantic matching: Match formulas based on meaning, not just syntax
- Caching: Cache embeddings for performance

Uses:
- Helps find relevant axioms for complex proofs
- Suggests similar formulas when exact match fails
- Enhances proof search with semantic understanding
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any, Tuple
import hashlib

# TDFOL imports
from ...TDFOL.tdfol_core import Formula

logger = logging.getLogger(__name__)


class EmbeddingEnhancedProver:
    """
    Prover that uses embeddings to find similar formulas and theorems.
    
    This provides a neural approach to theorem retrieval, complementing
    the symbolic TDFOL prover with semantic similarity matching.
    
    Example:
        >>> prover = EmbeddingEnhancedProver()
        >>> similarity = prover.compute_similarity(goal, axioms)
        >>> print(f"Similarity: {similarity:.3f}")
    """
    
    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        cache_enabled: bool = True
    ):
        """
        Initialize the embedding prover.
        
        Args:
            model_name: Name of the sentence transformer model to use
            cache_enabled: Whether to cache embeddings
        """
        self.model_name = model_name
        self.cache_enabled = cache_enabled
        self.embedding_cache: Dict[str, List[float]] = {}
        
        # Try to load sentence transformers
        self.model = None
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
            logger.info(f"Loaded embedding model: {model_name}")
        except ImportError:
            logger.warning("sentence-transformers not available, using fallback similarity")
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}, using fallback")
    
    def compute_similarity(
        self,
        goal: Formula,
        axioms: List[Formula],
        threshold: float = 0.7
    ) -> float:
        """
        Compute similarity between goal and axioms using embeddings.
        
        Args:
            goal: Goal formula to prove
            axioms: List of available axioms
            threshold: Minimum similarity threshold
        
        Returns:
            Maximum similarity score between goal and any axiom (0.0-1.0)
        """
        if not axioms:
            return 0.0
        
        # Convert formulas to strings
        goal_str = str(goal)
        axiom_strs = [str(ax) for ax in axioms]
        
        # If no embedding model, use simple string-based similarity
        if self.model is None:
            return self._fallback_similarity(goal_str, axiom_strs)
        
        # Compute embeddings
        goal_embedding = self._get_embedding(goal_str)
        axiom_embeddings = [self._get_embedding(ax_str) for ax_str in axiom_strs]
        
        # Compute cosine similarities
        similarities = [
            self._cosine_similarity(goal_embedding, ax_emb)
            for ax_emb in axiom_embeddings
        ]
        
        # Return maximum similarity
        max_similarity = max(similarities) if similarities else 0.0
        logger.debug(f"Max similarity for '{goal_str}': {max_similarity:.3f}")
        
        return max_similarity
    
    def find_similar_formulas(
        self,
        query: Formula,
        candidates: List[Formula],
        top_k: int = 5
    ) -> List[Tuple[Formula, float]]:
        """
        Find the most similar formulas to a query.
        
        Args:
            query: Query formula
            candidates: List of candidate formulas
            top_k: Number of top results to return
        
        Returns:
            List of (formula, similarity_score) tuples, sorted by similarity
        """
        if not candidates:
            return []
        
        query_str = str(query)
        
        # Compute similarity with each candidate
        similarities = []
        for candidate in candidates:
            candidate_str = str(candidate)
            if self.model is None:
                sim = self._fallback_similarity(query_str, [candidate_str])
            else:
                query_emb = self._get_embedding(query_str)
                cand_emb = self._get_embedding(candidate_str)
                sim = self._cosine_similarity(query_emb, cand_emb)
            
            similarities.append((candidate, sim))
        
        # Sort by similarity (descending) and return top k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]
    
    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text, using cache if available."""
        # Check cache
        if self.cache_enabled:
            cache_key = hashlib.md5(text.encode()).hexdigest()
            if cache_key in self.embedding_cache:
                return self.embedding_cache[cache_key]
        
        # Compute embedding
        if self.model is None:
            # Fallback: simple character-based vector
            embedding = [float(ord(c)) / 255.0 for c in text[:100]]
            embedding = embedding + [0.0] * (100 - len(embedding))  # Pad to 100
        else:
            embedding = self.model.encode(text).tolist()
        
        # Cache it
        if self.cache_enabled:
            self.embedding_cache[cache_key] = embedding
        
        return embedding
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if len(vec1) != len(vec2):
            raise ValueError(f"Vector dimensions don't match: {len(vec1)} vs {len(vec2)}")
        
        # Dot product
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        
        # Magnitudes
        mag1 = sum(a * a for a in vec1) ** 0.5
        mag2 = sum(b * b for b in vec2) ** 0.5
        
        # Avoid division by zero
        if mag1 == 0 or mag2 == 0:
            return 0.0
        
        return dot_product / (mag1 * mag2)
    
    def _fallback_similarity(self, goal: str, axioms: List[str]) -> float:
        """
        Fallback similarity when embeddings not available.
        
        Uses simple string matching heuristics:
        - Exact match: 1.0
        - Substring match: 0.7
        - Jaccard similarity on tokens: varies
        """
        max_sim = 0.0
        
        for axiom in axioms:
            # Exact match
            if goal == axiom:
                return 1.0
            
            # Substring match
            if goal in axiom or axiom in goal:
                max_sim = max(max_sim, 0.7)
                continue
            
            # Jaccard similarity on tokens
            goal_tokens = set(goal.replace('(', ' ').replace(')', ' ').split())
            axiom_tokens = set(axiom.replace('(', ' ').replace(')', ' ').split())
            
            intersection = len(goal_tokens & axiom_tokens)
            union = len(goal_tokens | axiom_tokens)
            
            if union > 0:
                jaccard = intersection / union
                max_sim = max(max_sim, jaccard * 0.6)  # Scale down a bit
        
        return max_sim
    
    def clear_cache(self):
        """Clear the embedding cache."""
        self.embedding_cache.clear()
        logger.info("Embedding cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get statistics about the embedding cache."""
        return {
            'cache_size': len(self.embedding_cache),
            'cache_enabled': self.cache_enabled,
            'model_loaded': self.model is not None,
            'model_name': self.model_name,
        }
