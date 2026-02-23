"""Semantic entity deduplication using embeddings for ontology validation.

This module provides embedding-based entity deduplication to complement the
string-based approach in OntologyValidator. It detects semantically similar
entities even when text differs significantly (e.g., "CEO" vs "Chief Executive Officer").
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable
import logging
import numpy as np

_logger = logging.getLogger(__name__)


@dataclass
class SemanticMergeSuggestion:
    """Suggestion to merge two semantically similar entities.
    
    Attributes:
        entity1_id: ID of first entity
        entity2_id: ID of second entity
        similarity_score: Cosine similarity score 0-1
        reason: Explanation for suggested merge
        evidence: Detailed evidence dict (semantic_similarity, name_similarity, etc.)
    """
    entity1_id: str
    entity2_id: str
    similarity_score: float
    reason: str
    evidence: Dict[str, Any]
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        return (f"SemanticMergeSuggestion({self.entity1_id} + {self.entity2_id}, "
                f"score={self.similarity_score:.3f}, reason={self.reason})")


class SemanticEntityDeduplicator:
    """Semantic entity deduplication using embedding vectors.
    
    Uses embeddings (sentence-transformers by default) to detect semantically
    similar entities that evade string-based matching. Ideal for:
    - Abbreviation expansion ("CEO" → "Chief Executive Officer")
    - Location variants ("NYC" → "New York City")
    - Synonyms ("attorney" → "lawyer")
    
    Example:
        >>> dedup = SemanticEntityDeduplicator()
        >>> ontology = {"entities": [...], "relationships": [...]}
        >>> suggestions = dedup.suggest_merges(ontology, threshold=0.88)
        >>> for sugg in suggestions:
        ...     print(f"Merge {sugg.entity1_id} + {sugg.entity2_id}")
    """
    
    def __init__(self, min_string_similarity: float = 0.3):
        """Initialize deduplicator.
        
        Args:
            min_string_similarity: Minimum string similarity (0-1) for including
                in evidence. Default 0.3. Lower values allow more diverse merges.
        """
        self.min_string_similarity = min_string_similarity
    
    def suggest_merges(
        self,
        ontology: Dict[str, Any],
        threshold: float = 0.85,
        max_suggestions: Optional[int] = None,
        embedding_fn: Optional[Callable[[List[str]], np.ndarray]] = None,
        batch_size: int = 32,
    ) -> List[SemanticMergeSuggestion]:
        """Suggest entity merges using semantic similarity.
        
        Args:
            ontology: Ontology dict with 'entities' and 'relationships'
            threshold: Minimum cosine similarity (0-1). Default 0.85.
            max_suggestions: Optional limit on suggestions. Default None (all).
            embedding_fn: Custom embedding function. Default uses sentence-transformers.
            batch_size: Batch size for embedding generation. Default 32.
        
        Returns:
            List of SemanticMergeSuggestion sorted by similarity (descending)
        
        Raises:
            ValueError: If ontology invalid or threshold out of range
            RuntimeError: If embedding generation fails
        """
        if not isinstance(ontology, dict):
            raise ValueError("ontology must be a dictionary")
        
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")
        
        entities = ontology.get("entities", [])
        relationships = ontology.get("relationships", [])
        
        if not isinstance(entities, list):
            raise ValueError("ontology['entities'] must be a list")
        
        if len(entities) < 2:
            _logger.info("Less than 2 entities, no semantic merges possible")
            return []
        
        # Get embeddings function
        if embedding_fn is None:
            embedding_fn = self._get_default_embedding_fn()
        
        # Extract entity data
        entity_data = self._extract_entity_data(entities)
        
        if len(entity_data) < 2:
            _logger.info("Less than 2 valid entities after filtering")
            return []
        
        # Generate embeddings
        try:
            texts = [e["text"] for e in entity_data]
            embeddings = self._batch_embed(texts, embedding_fn, batch_size)
            
            if embeddings is None or len(embeddings) != len(texts):
                raise RuntimeError("Embedding generation failed")
                
        except Exception as e:
            _logger.error(f"Failed to generate embeddings: {e}")
            raise RuntimeError(f"Embedding generation failed: {e}")
        
        # Normalize for cosine similarity
        embeddings_norm = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9)
        
        # Compute pairwise similarities
        similarity_matrix = np.dot(embeddings_norm, embeddings_norm.T)
        
        # Find pairs above threshold
        suggestions = self._find_merge_pairs(
            entity_data, similarity_matrix, threshold, relationships
        )
        
        # Sort and limit
        suggestions.sort(key=lambda s: s.similarity_score, reverse=True)
        
        if max_suggestions is not None:
            if max_suggestions > 0:
                suggestions = suggestions[:max_suggestions]
            else:
                suggestions = []
        
        _logger.info(
            f"Found {len(suggestions)} semantic merge suggestions (threshold={threshold})"
        )
        
        return suggestions
    
    def _extract_entity_data(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract relevant data from entity list."""
        entity_data = []
        
        for entity in entities:
            entity_id = entity.get("id") or entity.get("Id")
            text = entity.get("text") or entity.get("Text") or ""
            entity_type = entity.get("type") or entity.get("Type") or "Unknown"
            confidence = float(entity.get("confidence") or entity.get("Confidence") or 0.5)
            
            if not entity_id or not text:
                continue
            
            entity_data.append({
                "id": entity_id,
                "text": text,
                "type": entity_type,
                "confidence": confidence,
                "original": entity,
            })
        
        return entity_data
    
    def _find_merge_pairs(
        self,
        entity_data: List[Dict[str, Any]],
        similarity_matrix: np.ndarray,
        threshold: float,
        relationships: List[Dict[str, Any]],
    ) -> List[SemanticMergeSuggestion]:
        """Find entity pairs above similarity threshold."""
        suggestions = []
        
        for i in range(len(entity_data)):
            for j in range(i + 1, len(entity_data)):
                similarity = float(similarity_matrix[i, j])
                
                if similarity >= threshold:
                    entity1 = entity_data[i]
                    entity2 = entity_data[j]
                    
                    suggestion = self._build_merge_suggestion(
                        entity1, entity2, similarity, relationships
                    )
                    suggestions.append(suggestion)
        
        return suggestions
    
    def _build_merge_suggestion(
        self,
        entity1: Dict[str, Any],
        entity2: Dict[str, Any],
        semantic_similarity: float,
        relationships: List[Dict[str, Any]],
    ) -> SemanticMergeSuggestion:
        """Build a merge suggestion from similarity analysis."""
        from difflib import SequenceMatcher
        
        id1 = entity1["id"]
        id2 = entity2["id"]
        text1 = entity1["text"]
        text2 = entity2["text"]
        type1 = entity1["type"]
        type2 = entity2["type"]
        conf1 = entity1["confidence"]
        conf2 = entity2["confidence"]
        
        # Calculate string similarity for comparison
        name_similarity = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
        type_match = 1.0 if type1 == type2 else 0.0
        
        # Build evidence
        evidence = {
            "semantic_similarity": semantic_similarity,
            "name_similarity": name_similarity,
            "type_match": bool(type_match > 0.5),
            "type1": type1,
            "type2": type2,
            "confidence1": conf1,
            "confidence2": conf2,
            "confidence_difference": abs(conf1 - conf2),
            "method": "embedding-based",
        }
        
        # Build reason string
        reasons = []
        if semantic_similarity >= 0.95:
            reasons.append("very high semantic similarity")
        elif semantic_similarity >= 0.90:
            reasons.append("high semantic similarity")
        else:
            reasons.append("semantic similarity")
        
        if type_match > 0.5:
            reasons.append("same entity type")
        
        if name_similarity < 0.5:
            reasons.append("different text representations")
        
        reason = "; ".join(reasons)
        
        return SemanticMergeSuggestion(
            entity1_id=id1,
            entity2_id=id2,
            similarity_score=semantic_similarity,
            reason=reason,
            evidence=evidence,
        )
    
    def _get_default_embedding_fn(self) -> Callable[[List[str]], np.ndarray]:
        """Get default embedding function using sentence-transformers."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not available. Install with: "
                "pip install sentence-transformers"
            )
        
        model_name = "all-MiniLM-L6-v2"  # 384-dim, fast
        _logger.info(f"Loading sentence-transformers model: {model_name}")
        
        try:
            model = SentenceTransformer(model_name)
        except Exception as e:
            _logger.warning(f"Failed to load {model_name}: {e}. Trying fallback...")
            model = SentenceTransformer("paraphrase-MiniLM-L3-v2")
        
        def embed_fn(texts: List[str]) -> np.ndarray:
            if not texts:
                return np.array([])
            return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        
        return embed_fn
    
    def _batch_embed(
        self,
        texts: List[str],
        embedding_fn: Callable[[List[str]], np.ndarray],
        batch_size: int,
    ) -> np.ndarray:
        """Generate embeddings in batches."""
        if not texts:
            return np.array([])
        
        embeddings_list = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = embedding_fn(batch)
            embeddings_list.append(batch_embeddings)
        
        return np.vstack(embeddings_list)
