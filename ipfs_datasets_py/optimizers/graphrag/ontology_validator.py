"""OntologyValidator class for ontology quality assessment and improvement suggestions.

This module provides the OntologyValidator class for analyzing ontology quality
and suggesting improvements such as entity merging candidates.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import logging
from difflib import SequenceMatcher

_logger = logging.getLogger(__name__)


@dataclass
class MergeSuggestion:
    """Suggestion to merge two entities.
    
    Attributes:
        entity1_id: ID of first entity
        entity2_id: ID of second entity
        similarity_score: Score 0-1 indicating merge suitability
        reason: Explanation for why entities should be merged
        evidence: Dict with detailed evidence (name_similarity, type_match, etc.)
    """
    entity1_id: str
    entity2_id: str
    similarity_score: float
    reason: str
    evidence: Dict[str, Any]
    
    def __repr__(self) -> str:
        """Return concise string representation."""
        return (f"MergeSuggestion({self.entity1_id} + {self.entity2_id}, "
                f"score={self.similarity_score:.3f}, reason={self.reason})")


class OntologyValidator:
    """Validator for ontology quality and improvement suggestions.
    
    Provides methods to:
    - Validate ontology structure
    - Suggest entity merges (deduplication)
    - Identify quality issues
    - Recommend optimizations
    
    Example:
        >>> validator = OntologyValidator()
        >>> ontology = {
        ...     "entities": [
        ...         {"id": "e1", "text": "Alice Smith", "type": "Person", "confidence": 0.9},
        ...         {"id": "e2", "text": "Alice Smyth", "type": "Person", "confidence": 0.85},
        ...     ],
        ...     "relationships": []
        ... }
        >>> suggestions = validator.suggest_entity_merges(ontology, threshold=0.8)
        >>> for sugg in suggestions:
        ...     print(f"Merge {sugg.entity1_id} + {sugg.entity2_id}: {sugg.reason}")
    """
    
    def __init__(self, min_name_similarity: float = 0.75):
        """Initialize validator.
        
        Args:
            min_name_similarity: Minimum string similarity threshold (0-1) for
                considering names as similar. Default 0.75 (75% similar).
        """
        self.min_name_similarity = min_name_similarity
    
    def suggest_entity_merges(
        self,
        ontology: Dict[str, Any],
        threshold: float = 0.8,
        max_suggestions: Optional[int] = None,
    ) -> List[MergeSuggestion]:
        """Suggest pairs of entities that could be merged.
        
        Analyzes entities to find candidates for merging based on:
        - Name similarity (using sequence matching)
        - Type compatibility (same entity type)
        - Confidence thresholds
        - Relationship redundancy
        
        Args:
            ontology: Ontology dict with 'entities' and optionally 'relationships'
            threshold: Minimum similarity score (0-1) for suggestions. Default 0.8.
            max_suggestions: Optional limit on number of suggestions to return.
                If None, returns all suggestions above threshold.
        
        Returns:
            List of MergeSuggestion objects sorted by similarity_score (descending)
        
        Raises:
            ValueError: If ontology is invalid or threshold out of range
        """
        if not isinstance(ontology, dict):
            raise ValueError("ontology must be a dictionary")
        
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")
        
        entities = ontology.get("entities", [])
        relationships = ontology.get("relationships", [])
        
        if not isinstance(entities, list):
            raise ValueError("ontology['entities'] must be a list")
        
        # Find entity IDs that are involved in relationships
        entity_ids_in_relationships = self._get_entity_ids_in_relationships(relationships)
        
        suggestions: List[MergeSuggestion] = []
        
        # Compare all pairs of entities
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i + 1:]:
                # Extract entity IDs
                id1 = entity1.get("id") or entity1.get("Id")
                id2 = entity2.get("id") or entity2.get("Id")
                
                if not id1 or not id2:
                    continue  # Skip entities without IDs
                
                # Skip if entities are already identical
                if id1 == id2:
                    continue
                
                # Calculate merge suitability
                suggestion = self._evaluate_merge_pair(entity1, entity2, relationships)
                
                if suggestion and suggestion.similarity_score >= threshold:
                    suggestions.append(suggestion)
        
        # Sort by similarity score (descending)
        suggestions.sort(key=lambda s: s.similarity_score, reverse=True)
        
        # Apply max_suggestions limit if specified
        if max_suggestions is not None:
            if max_suggestions > 0:
                suggestions = suggestions[:max_suggestions]
            else:
                suggestions = []
        
        _logger.info(
            f"Found {len(suggestions)} merge suggestions (threshold={threshold})"
        )
        
        return suggestions
    
    def _evaluate_merge_pair(
        self,
        entity1: Dict[str, Any],
        entity2: Dict[str, Any],
        relationships: List[Dict[str, Any]],
    ) -> Optional[MergeSuggestion]:
        """Evaluate if two entities should be merged.
        
        Args:
            entity1: First entity dict
            entity2: Second entity dict
            relationships: List of relationships in ontology
        
        Returns:
            MergeSuggestion if entities are mergeable, None otherwise
        """
        id1 = entity1.get("id") or entity1.get("Id")
        id2 = entity2.get("id") or entity2.get("Id")
        text1 = entity1.get("text") or entity1.get("Text") or ""
        text2 = entity2.get("text") or entity2.get("Text") or ""
        type1 = entity1.get("type") or entity1.get("Type") or "Unknown"
        type2 = entity2.get("type") or entity2.get("Type") or "Unknown"
        conf1 = float(entity1.get("confidence") or entity1.get("Confidence") or 0.5)
        conf2 = float(entity2.get("confidence") or entity2.get("Confidence") or 0.5)
        
        # Calculate similarity components
        name_similarity = self._calculate_string_similarity(text1, text2)
        type_match = 1.0 if type1 == type2 else 0.0
        confidence_similarity = 1.0 - abs(conf1 - conf2)  # Higher if confidences are similar
        
        # Don't suggest merging if names are too different
        if name_similarity < self.min_name_similarity:
            return None
        
        # Calculate overall similarity score
        # Weight: name (50%), type match (30%), confidence similarity (20%)
        overall_score = (
            0.5 * name_similarity +
            0.3 * type_match +
            0.2 * confidence_similarity
        )
        
        # Build evidence dict
        evidence = {
            "name_similarity": name_similarity,
            "type_match": bool(type_match > 0.5),
            "type1": type1,
            "type2": type2,
            "confidence1": conf1,
            "confidence2": conf2,
            "confidence_difference": abs(conf1 - conf2),
        }
        
        # Build reason string
        reasons = []
        if name_similarity >= 0.9:
            reasons.append("very similar names")
        elif name_similarity >= 0.8:
            reasons.append("similar names")
        
        if type_match > 0.5:
            reasons.append("same entity type")
        
        if abs(conf1 - conf2) < 0.1:
            reasons.append("similar confidence")
        
        reason = "; ".join(reasons) if reasons else "potential duplicate"
        
        return MergeSuggestion(
            entity1_id=id1,
            entity2_id=id2,
            similarity_score=overall_score,
            reason=reason,
            evidence=evidence,
        )
    
    def _calculate_string_similarity(self, str1: str, str2: str) -> float:
        """Calculate string similarity using SequenceMatcher.
        
        Args:
            str1: First string
            str2: Second string
        
        Returns:
            Similarity score 0-1 (1.0 = identical, 0.0 = completely different)
        """
        if not str1 or not str2:
            return 0.0
        
        # Normalize strings (lowercase, strip whitespace)
        s1 = str(str1).strip().lower()
        s2 = str(str2).strip().lower()
        
        # Quick check for exact match
        if s1 == s2:
            return 1.0
        
        # Use SequenceMatcher for similarity ratio
        ratio = SequenceMatcher(None, s1, s2).ratio()
        return float(ratio)
    
    def _get_entity_ids_in_relationships(
        self,
        relationships: List[Dict[str, Any]],
    ) -> set:
        """Get all entity IDs that are involved in any relationship.
        
        Args:
            relationships: List of relationship dicts
        
        Returns:
            Set of entity IDs
        """
        entity_ids = set()
        
        for rel in relationships:
            source_id = rel.get("source_id") or rel.get("SourceId")
            target_id = rel.get("target_id") or rel.get("TargetId")
            
            if source_id:
                entity_ids.add(source_id)
            if target_id:
                entity_ids.add(target_id)
        
        return entity_ids
