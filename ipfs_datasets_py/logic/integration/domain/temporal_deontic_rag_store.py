"""
Temporal Deontic Logic RAG Store

This module implements a specialized vector store for temporal deontic logic theorems
that can be queried for document consistency checking. It functions like a debugger's
symbol table for legal documents.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple, Set, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import numpy as np
import hashlib
import json

from ..converters.deontic_logic_core import (
    DeonticFormula, DeonticOperator, DeonticRuleSet, TemporalCondition, 
    TemporalOperator, LegalAgent, LegalContext
)
from .deontic_query_engine import DeonticQueryEngine, QueryResult, QueryType
# Import from relative paths, with fallbacks
try:
    from ..vector_stores.base import BaseVectorStore
    from ..embeddings.base import BaseEmbedding
except ImportError:
    # Fallback base classes for when vector stores aren't available
    class BaseVectorStore:
        def add_vectors(self, vectors, ids, metadata):
            pass
    
    class BaseEmbedding:
        def embed_text(self, text):
            return np.random.random(768)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TheoremMetadata:
    """Metadata for a deontic logic theorem in the RAG store."""
    theorem_id: str
    formula: DeonticFormula
    embedding: np.ndarray
    temporal_scope: Tuple[Optional[datetime], Optional[datetime]]  # (start, end)
    jurisdiction: Optional[str] = None
    legal_domain: Optional[str] = None
    confidence: float = 1.0
    source_case: Optional[str] = None
    precedent_strength: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)
    
    def __hash__(self):
        """Make TheoremMetadata hashable based on theorem_id."""
        return hash(self.theorem_id)
    
    def __eq__(self, other):
        """Equality comparison based on theorem_id."""
        if not isinstance(other, TheoremMetadata):
            return False
        return self.theorem_id == other.theorem_id


@dataclass
class ConsistencyResult:
    """Result of a document consistency check."""
    is_consistent: bool
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    relevant_theorems: List[TheoremMetadata] = field(default_factory=list)
    confidence_score: float = 0.0
    reasoning: str = ""
    temporal_conflicts: List[Dict[str, Any]] = field(default_factory=list)


class TemporalDeonticRAGStore:
    """
    A specialized RAG store for temporal deontic logic theorems.
    
    This class provides RAG capabilities specifically designed for legal document
    consistency checking against temporal deontic logic theorems derived from caselaw.
    It functions like a debugger for legal documents.
    """
    
    def __init__(self, 
                 vector_store: Optional[BaseVectorStore] = None,
                 embedding_model: Optional[BaseEmbedding] = None,
                 query_engine: Optional[DeonticQueryEngine] = None):
        """
        Initialize the temporal deontic RAG store.
        
        Args:
            vector_store: Vector store backend for embeddings
            embedding_model: Model for generating embeddings
            query_engine: Deontic logic query engine
        """
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.query_engine = query_engine or DeonticQueryEngine()
        
        # In-memory theorem storage (can be backed by vector store)
        self.theorems: Dict[str, TheoremMetadata] = {}
        self.temporal_index: Dict[str, List[str]] = {}  # time_key -> theorem_ids
        self.domain_index: Dict[str, List[str]] = {}    # domain -> theorem_ids
        self.jurisdiction_index: Dict[str, List[str]] = {}  # jurisdiction -> theorem_ids
        
        logger.info("Initialized TemporalDeonticRAGStore")
    
    def add_theorem(self, formula: DeonticFormula, 
                   temporal_scope: Tuple[Optional[datetime], Optional[datetime]] = (None, None),
                   jurisdiction: Optional[str] = None,
                   legal_domain: Optional[str] = None,
                   source_case: Optional[str] = None,
                   precedent_strength: float = 1.0) -> str:
        """
        Add a deontic logic theorem to the RAG store.
        
        Args:
            formula: The deontic logic formula
            temporal_scope: Time period when this theorem applies (start, end)
            jurisdiction: Legal jurisdiction
            legal_domain: Domain of law (contract, tort, etc.)
            source_case: Source case or legal document
            precedent_strength: Strength of this precedent (0.0-1.0)
            
        Returns:
            theorem_id: Unique identifier for the theorem
        """
        # Generate theorem ID
        formula_str = formula.to_fol_string() if hasattr(formula, 'to_fol_string') else str(formula)
        theorem_id = hashlib.md5(f"{formula_str}:{temporal_scope}:{jurisdiction}".encode()).hexdigest()
        
        # Generate embedding if model available
        embedding = None
        if self.embedding_model:
            try:
                embedding = self.embedding_model.embed_text(formula_str)
            except Exception as e:
                logger.warning(f"Failed to generate embedding for theorem {theorem_id}: {e}")
                # Use dummy embedding for now
                embedding = np.random.random(768)
        else:
            # Use dummy embedding if no model available
            embedding = np.random.random(768)
        
        # Create theorem metadata
        metadata = TheoremMetadata(
            theorem_id=theorem_id,
            formula=formula,
            embedding=embedding,
            temporal_scope=temporal_scope,
            jurisdiction=jurisdiction,
            legal_domain=legal_domain,
            source_case=source_case,
            precedent_strength=precedent_strength
        )
        
        # Store theorem
        self.theorems[theorem_id] = metadata
        
        # Update indexes
        self._update_temporal_index(theorem_id, temporal_scope)
        if legal_domain:
            self._update_domain_index(theorem_id, legal_domain)
        if jurisdiction:
            self._update_jurisdiction_index(theorem_id, jurisdiction)
        
        # Add to vector store if available
        if self.vector_store and embedding is not None:
            try:
                self.vector_store.add_vectors([embedding], [theorem_id], [{"formula": formula_str}])
            except Exception as e:
                logger.warning(f"Failed to add theorem to vector store: {e}")
        
        logger.info(f"Added theorem {theorem_id}: {formula_str[:100]}...")
        return theorem_id
    
    def retrieve_relevant_theorems(self, 
                                 query_formula: DeonticFormula,
                                 temporal_context: Optional[datetime] = None,
                                 jurisdiction: Optional[str] = None,
                                 legal_domain: Optional[str] = None,
                                 top_k: int = 10) -> List[TheoremMetadata]:
        """
        Retrieve theorems relevant to a query formula using RAG.
        
        Args:
            query_formula: The formula to find relevant theorems for
            temporal_context: Time context for temporal filtering
            jurisdiction: Filter by jurisdiction
            legal_domain: Filter by legal domain
            top_k: Number of top results to return
            
        Returns:
            List of relevant theorem metadata sorted by relevance
        """
        relevant_theorems = []
        
        # Generate embedding for query
        query_text = query_formula.to_fol_string() if hasattr(query_formula, 'to_fol_string') else str(query_formula)
        
        if self.embedding_model:
            try:
                query_embedding = self.embedding_model.embed_text(query_text)
            except Exception as e:
                logger.warning(f"Failed to generate query embedding: {e}")
                query_embedding = np.random.random(768)
        else:
            query_embedding = np.random.random(768)
        
        # Filter candidates by constraints
        candidate_ids = set(self.theorems.keys())
        
        # Apply temporal filtering
        if temporal_context:
            temporal_candidates = self._filter_by_temporal_context(temporal_context)
            candidate_ids &= set(temporal_candidates)
        
        # Apply jurisdiction filtering
        if jurisdiction and jurisdiction in self.jurisdiction_index:
            candidate_ids &= set(self.jurisdiction_index[jurisdiction])
        
        # Apply domain filtering
        if legal_domain and legal_domain in self.domain_index:
            candidate_ids &= set(self.domain_index[legal_domain])
        
        # Calculate similarities and rank
        scored_theorems = []
        for theorem_id in candidate_ids:
            theorem = self.theorems[theorem_id]
            
            # Calculate embedding similarity
            if theorem.embedding is not None:
                similarity = self._cosine_similarity(query_embedding, theorem.embedding)
            else:
                similarity = 0.5  # Default similarity
            
            # Apply precedent strength weighting
            weighted_score = similarity * theorem.precedent_strength
            
            scored_theorems.append((weighted_score, theorem))
        
        # Sort by score and return top_k
        scored_theorems.sort(key=lambda x: x[0], reverse=True)
        relevant_theorems = [theorem for _, theorem in scored_theorems[:top_k]]
        
        logger.info(f"Retrieved {len(relevant_theorems)} relevant theorems for query")
        return relevant_theorems
    
    def check_document_consistency(self, 
                                 document_formulas: List[DeonticFormula],
                                 temporal_context: Optional[datetime] = None,
                                 jurisdiction: Optional[str] = None,
                                 legal_domain: Optional[str] = None) -> ConsistencyResult:
        """
        Check consistency of document formulas against existing theorems.
        
        This is the main "debugger" functionality that checks if a document's
        deontic logic is consistent with existing legal theorems.
        
        Args:
            document_formulas: Formulas extracted from the document
            temporal_context: Time context for the document
            jurisdiction: Relevant jurisdiction
            legal_domain: Relevant legal domain
            
        Returns:
            ConsistencyResult with conflicts and explanations
        """
        conflicts = []
        all_relevant_theorems = []
        temporal_conflicts = []
        
        # Check each formula against relevant theorems
        for doc_formula in document_formulas:
            relevant_theorems = self.retrieve_relevant_theorems(
                doc_formula, temporal_context, jurisdiction, legal_domain, top_k=20
            )
            all_relevant_theorems.extend(relevant_theorems)
            
            # Check for direct logical conflicts
            for theorem in relevant_theorems:
                conflict = self._check_formula_conflict(doc_formula, theorem.formula)
                if conflict:
                    conflicts.append({
                        "type": "logical_conflict",
                        "document_formula": doc_formula.to_fol_string() if hasattr(doc_formula, 'to_fol_string') else str(doc_formula),
                        "conflicting_theorem": theorem.theorem_id,
                        "theorem_formula": theorem.formula.to_fol_string() if hasattr(theorem.formula, 'to_fol_string') else str(theorem.formula),
                        "source_case": theorem.source_case,
                        "confidence": theorem.confidence,
                        "description": conflict
                    })
            
            # Check for temporal conflicts
            if temporal_context:
                temporal_conflict = self._check_temporal_conflicts(doc_formula, relevant_theorems, temporal_context)
                if temporal_conflict:
                    temporal_conflicts.append(temporal_conflict)
        
        # Calculate overall consistency
        is_consistent = len(conflicts) == 0 and len(temporal_conflicts) == 0
        confidence_score = self._calculate_consistency_confidence(conflicts, temporal_conflicts, all_relevant_theorems)
        
        # Generate reasoning
        reasoning = self._generate_consistency_reasoning(conflicts, temporal_conflicts, all_relevant_theorems)
        
        return ConsistencyResult(
            is_consistent=is_consistent,
            conflicts=conflicts,
            relevant_theorems=self._deduplicate_theorems(all_relevant_theorems),  # Remove duplicates
            confidence_score=confidence_score,
            reasoning=reasoning,
            temporal_conflicts=temporal_conflicts
        )
    
    def _deduplicate_theorems(self, theorems: List[TheoremMetadata]) -> List[TheoremMetadata]:
        """Remove duplicate theorems based on theorem_id."""
        seen_ids = set()
        unique_theorems = []
        for theorem in theorems:
            if theorem.theorem_id not in seen_ids:
                seen_ids.add(theorem.theorem_id)
                unique_theorems.append(theorem)
        return unique_theorems
    
    def _update_temporal_index(self, theorem_id: str, temporal_scope: Tuple[Optional[datetime], Optional[datetime]]):
        """Update the temporal index with a new theorem."""
        start, end = temporal_scope
        
        if start:
            time_key = start.strftime("%Y-%m")
            if time_key not in self.temporal_index:
                self.temporal_index[time_key] = []
            self.temporal_index[time_key].append(theorem_id)
        
        if end:
            time_key = end.strftime("%Y-%m")
            if time_key not in self.temporal_index:
                self.temporal_index[time_key] = []
            self.temporal_index[time_key].append(theorem_id)
    
    def _update_domain_index(self, theorem_id: str, legal_domain: str):
        """Update the domain index with a new theorem."""
        if legal_domain not in self.domain_index:
            self.domain_index[legal_domain] = []
        self.domain_index[legal_domain].append(theorem_id)
    
    def _update_jurisdiction_index(self, theorem_id: str, jurisdiction: str):
        """Update the jurisdiction index with a new theorem."""
        if jurisdiction not in self.jurisdiction_index:
            self.jurisdiction_index[jurisdiction] = []
        self.jurisdiction_index[jurisdiction].append(theorem_id)
    
    def _filter_by_temporal_context(self, temporal_context: datetime) -> List[str]:
        """Filter theorems by temporal context."""
        relevant_ids = []
        time_key = temporal_context.strftime("%Y-%m")
        
        # Get theorems from the same time period
        if time_key in self.temporal_index:
            relevant_ids.extend(self.temporal_index[time_key])
        
        # Also check theorems with overlapping temporal scopes
        for theorem_id, theorem in self.theorems.items():
            start, end = theorem.temporal_scope
            if self._temporal_overlap(temporal_context, start, end):
                relevant_ids.append(theorem_id)
        
        return list(set(relevant_ids))
    
    def _temporal_overlap(self, context_time: datetime, start: Optional[datetime], end: Optional[datetime]) -> bool:
        """Check if a time context overlaps with a temporal scope."""
        if start is None and end is None:
            return True  # Always applicable
        if start is None:
            return context_time <= end
        if end is None:
            return context_time >= start
        return start <= context_time <= end
    
    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        try:
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return dot_product / (norm1 * norm2)
        except (ValueError, TypeError, AttributeError) as e:
            # numpy operations can fail if inputs aren't proper arrays
            logger.debug(f"Could not compute cosine similarity: {e}")
            return 0.0
    
    def _check_formula_conflict(self, formula1: DeonticFormula, formula2: DeonticFormula) -> Optional[str]:
        """Check if two formulas conflict with each other."""
        # Basic conflict detection - can be enhanced with theorem proving
        
        # Check for direct contradictions in deontic operators
        if (formula1.operator == DeonticOperator.OBLIGATION and 
            formula2.operator == DeonticOperator.PROHIBITION and
            self._same_proposition(formula1.proposition, formula2.proposition)):
            return f"Obligation to '{formula1.proposition}' conflicts with prohibition of '{formula2.proposition}'"
        
        if (formula1.operator == DeonticOperator.PERMISSION and 
            formula2.operator == DeonticOperator.PROHIBITION and
            self._same_proposition(formula1.proposition, formula2.proposition)):
            return f"Permission for '{formula1.proposition}' conflicts with prohibition of '{formula2.proposition}'"
        
        # Check for semantic conflicts with keyword matching
        prop1_lower = formula1.proposition.lower()
        prop2_lower = formula2.proposition.lower()
        
        # Confidentiality conflicts
        if (("disclose" in prop1_lower or "share" in prop1_lower) and
            ("confidential" in prop1_lower or "confidential" in prop2_lower) and
            formula1.operator == DeonticOperator.PERMISSION and
            formula2.operator == DeonticOperator.PROHIBITION):
            return f"Permission to disclose conflicts with confidentiality prohibition"
        
        # Notice requirement conflicts  
        if (("notice" in prop1_lower and "notice" in prop2_lower) and
            (("provide" in prop1_lower and "not" in prop2_lower) or
             ("shall not provide" in prop1_lower and "must provide" in prop2_lower))):
            return f"Notice requirements conflict between formulas"
        
        return None
    
    def _same_proposition(self, prop1: str, prop2: str) -> bool:
        """Check if two propositions refer to the same concept."""
        # Enhanced semantic matching
        prop1_clean = prop1.lower().strip()
        prop2_clean = prop2.lower().strip()
        
        # Exact match
        if prop1_clean == prop2_clean:
            return True
        
        # Check for key concept overlaps
        key_terms1 = set(prop1_clean.split())
        key_terms2 = set(prop2_clean.split())
        
        # High overlap indicates same concept
        overlap = len(key_terms1 & key_terms2)
        total_unique = len(key_terms1 | key_terms2)
        
        if total_unique > 0 and overlap / total_unique > 0.6:
            return True
        
        return False
    
    def _check_temporal_conflicts(self, formula: DeonticFormula, theorems: List[TheoremMetadata], 
                                context_time: datetime) -> Optional[Dict[str, Any]]:
        """Check for temporal conflicts with existing theorems."""
        for theorem in theorems:
            start, end = theorem.temporal_scope
            if not self._temporal_overlap(context_time, start, end):
                return {
                    "type": "temporal_conflict",
                    "document_formula": formula.to_fol_string() if hasattr(formula, 'to_fol_string') else str(formula),
                    "conflicting_theorem": theorem.theorem_id,
                    "context_time": context_time.isoformat(),
                    "theorem_temporal_scope": (
                        start.isoformat() if start else None,
                        end.isoformat() if end else None
                    ),
                    "description": f"Formula applies at {context_time} but theorem is only valid from {start} to {end}"
                }
        return None
    
    def _calculate_consistency_confidence(self, conflicts: List[Dict], temporal_conflicts: List[Dict], 
                                        theorems: List[TheoremMetadata]) -> float:
        """Calculate confidence score for consistency result."""
        if not theorems:
            return 0.0
        
        base_confidence = 1.0
        
        # Reduce confidence for each conflict
        conflict_penalty = len(conflicts) * 0.3
        temporal_penalty = len(temporal_conflicts) * 0.2
        
        # Increase confidence based on theorem strength
        theorem_boost = sum(t.precedent_strength for t in theorems) / len(theorems) * 0.1
        
        final_confidence = max(0.0, min(1.0, base_confidence - conflict_penalty - temporal_penalty + theorem_boost))
        return final_confidence
    
    def _generate_consistency_reasoning(self, conflicts: List[Dict], temporal_conflicts: List[Dict], 
                                      theorems: List[TheoremMetadata]) -> str:
        """Generate human-readable reasoning for the consistency result."""
        reasoning_parts = []
        
        if not conflicts and not temporal_conflicts:
            reasoning_parts.append(f"Document is consistent with {len(theorems)} relevant legal theorems.")
        else:
            reasoning_parts.append(f"Found {len(conflicts)} logical conflicts and {len(temporal_conflicts)} temporal conflicts.")
        
        if conflicts:
            reasoning_parts.append("Logical conflicts:")
            for conflict in conflicts[:3]:  # Show first 3 conflicts
                reasoning_parts.append(f"  - {conflict.get('description', 'Conflict detected')}")
        
        if temporal_conflicts:
            reasoning_parts.append("Temporal conflicts:")
            for conflict in temporal_conflicts[:3]:  # Show first 3 conflicts
                reasoning_parts.append(f"  - {conflict.get('description', 'Temporal conflict detected')}")
        
        reasoning_parts.append(f"Analysis based on {len(theorems)} relevant theorems from legal precedents.")
        
        return "\n".join(reasoning_parts)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the theorem store."""
        return {
            "total_theorems": len(self.theorems),
            "jurisdictions": len(self.jurisdiction_index),
            "legal_domains": len(self.domain_index),
            "temporal_periods": len(self.temporal_index),
            "avg_precedent_strength": sum(t.precedent_strength for t in self.theorems.values()) / len(self.theorems) if self.theorems else 0.0
        }