"""
Hybrid Document Indexer

Combines ipfs_datasets_py's vector embeddings with HACC's keyword-based tagging
for optimal document indexing and search.

This provides the best of both approaches:
- Semantic search via vector embeddings (ipfs_datasets_py)
- Domain-specific keyword matching (HACC)
- Combined relevance scoring
"""

import sys
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Add ipfs_datasets_py to path if available
ipfs_datasets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ipfs_datasets_py')
if os.path.exists(ipfs_datasets_path) and ipfs_datasets_path not in sys.path:
    sys.path.insert(0, ipfs_datasets_path)

try:
    from ipfs_datasets_py.embeddings_router import EmbeddingsRouter
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    EmbeddingsRouter = None

from .keywords import get_keywords, get_type_specific_keywords
from .legal_patterns import LegalPatternExtractor
from .risk_scoring import ComplaintRiskScorer


class HybridDocumentIndexer:
    """
    Hybrid indexer combining vector embeddings with keyword tagging.
    
    This class provides:
    1. Vector embeddings for semantic search (ipfs_datasets_py)
    2. Keyword extraction and tagging (HACC)
    3. Legal provision extraction (HACC)
    4. Risk scoring (HACC)
    5. Combined relevance scoring
    
    Example:
        >>> indexer = HybridDocumentIndexer()
        >>> result = await indexer.index_document(text, metadata)
        >>> print(f"Risk: {result['risk_score']}, Keywords: {result['keywords']}")
    """
    
    def __init__(self, enable_embeddings: bool = True):
        """
        Initialize the hybrid indexer.
        
        Args:
            enable_embeddings: Whether to enable vector embeddings (requires ipfs_datasets_py)
        """
        self.enable_embeddings = enable_embeddings and EMBEDDINGS_AVAILABLE
        
        # Initialize ipfs_datasets_py components
        if self.enable_embeddings:
            try:
                self.embeddings_router = EmbeddingsRouter()
            except Exception as e:
                logger.warning(f"Failed to initialize embeddings: {e}")
                self.embeddings_router = None
                self.enable_embeddings = False
        else:
            self.embeddings_router = None
        
        # Initialize HACC components
        self.legal_extractor = LegalPatternExtractor()
        self.risk_scorer = ComplaintRiskScorer()
    
    async def index_document(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Index a document with both vector embeddings and keyword tagging.
        
        Args:
            text: Document text to index
            metadata: Optional metadata about the document
            
        Returns:
            Dictionary containing:
            - embedding: Vector embedding (if enabled)
            - keywords: Extracted keywords
            - legal_provisions: Found legal provisions
            - risk_score: Risk assessment
            - applicability: Domain tags
            - indexed_date: Timestamp
        """
        result = {
            'text_length': len(text),
            'metadata': metadata or {},
            'indexed_date': datetime.now().isoformat()
        }
        
        # Generate vector embedding (ipfs_datasets_py)
        if self.enable_embeddings and self.embeddings_router:
            try:
                embedding = await self.embeddings_router.embed_text(text)
                result['embedding'] = embedding
                result['embedding_available'] = True
            except Exception as e:
                print(f"Warning: Embedding failed: {e}")
                result['embedding_available'] = False
        else:
            result['embedding_available'] = False
        
        # Extract keywords (using new function)
        complaint_keywords = self._extract_keywords(text, get_keywords('complaint'))
        evidence_keywords = self._extract_keywords(text, get_keywords('evidence'))
        legal_keywords = self._extract_keywords(text, get_keywords('legal'))
        binding_keywords = self._extract_keywords(text, get_keywords('binding'))
        
        result['keywords'] = {
            'complaint': complaint_keywords,
            'evidence': evidence_keywords,
            'legal': legal_keywords,
            'binding': binding_keywords
        }
        
        # Tag applicability (HACC)
        applicability = self._tag_applicability(text)
        result['applicability'] = applicability
        
        # Extract legal provisions (HACC)
        legal_result = self.legal_extractor.extract_provisions(text)
        result['legal_provisions'] = legal_result
        
        # Calculate risk score (HACC)
        risk_result = self.risk_scorer.calculate_risk(text, legal_result['provisions'])
        result['risk_score'] = risk_result['score']
        result['risk_level'] = risk_result['level']
        result['risk_factors'] = risk_result['factors']
        
        # Calculate combined relevance score
        result['relevance_score'] = self._calculate_relevance(result)
        
        return result
    
    def _extract_keywords(self, text: str, keyword_list: List[str]) -> List[str]:
        """Extract keywords from text (case-insensitive)."""
        found = []
        text_lower = text.lower()
        for kw in keyword_list:
            if kw.lower() in text_lower:
                found.append(kw)
        return list(set(found))  # dedupe
    
    def _tag_applicability(self, text: str) -> List[str]:
        """
        Tag document with applicability areas.
        
        Uses type-specific keywords only to avoid false positives from
        global keywords that appear in all complaint types.
        """
        tags = []
        text_lower = text.lower()
        
        # Check for different complaint types using type-specific keywords only
        complaint_types = ['housing', 'employment', 'civil_rights', 'consumer', 'healthcare']
        for ctype in complaint_types:
            # Use type-specific keywords to avoid false positives
            keywords = get_type_specific_keywords('complaint', ctype)
            if not keywords:
                continue
            
            # Require multiple matches for confidence
            matches = sum(1 for kw in keywords if kw.lower() in text_lower)
            if matches >= 2:  # Require at least 2 type-specific keywords
                tags.append(ctype)
        
        return tags
    
    def _calculate_relevance(self, index_result: Dict[str, Any]) -> float:
        """
        Calculate combined relevance score.
        
        Combines:
        - Keyword count (weighted by type)
        - Legal provision count
        - Risk score
        - Applicability breadth
        
        Returns a score from 0.0 to 1.0
        """
        # Keyword scoring
        keyword_score = 0.0
        keyword_score += len(index_result['keywords']['complaint']) * 0.3
        keyword_score += len(index_result['keywords']['legal']) * 0.2
        keyword_score += len(index_result['keywords']['binding']) * 0.15
        keyword_score += len(index_result['keywords']['evidence']) * 0.1
        
        # Legal provisions scoring
        provision_score = min(index_result['legal_provisions']['provision_count'] * 0.1, 1.0)
        
        # Risk scoring
        risk_score = index_result['risk_score'] / 3.0  # Normalize to 0-1
        
        # Applicability scoring
        applicability_score = min(len(index_result['applicability']) * 0.2, 1.0)
        
        # Combined score (weighted average)
        combined = (
            keyword_score * 0.4 +
            provision_score * 0.2 +
            risk_score * 0.3 +
            applicability_score * 0.1
        )
        
        # Normalize to 0-1 range
        return min(combined, 1.0)
    
    async def search(self, query: str, top_k: int = 10, 
                    filter_by: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Hybrid search combining vector similarity and keyword matching.
        
        Args:
            query: Search query
            top_k: Number of results to return
            filter_by: Optional filters (e.g., {'applicability': 'housing'})
            
        Returns:
            List of matching documents sorted by combined relevance
        """
        # This would integrate with a vector database and DuckDB
        # For now, return structure for future implementation
        raise NotImplementedError(
            "Hybrid search requires integration with vector database and DuckDB. "
            "Use index_document() to prepare documents, then query via mediator hooks."
        )
    
    def get_statistics(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get statistics about indexed documents.
        
        Args:
            documents: List of indexed document results
            
        Returns:
            Statistics including risk distribution, keyword frequencies, etc.
        """
        if not documents:
            return {'total': 0}
        
        stats = {
            'total': len(documents),
            'risk_distribution': {'high': 0, 'medium': 0, 'low': 0, 'minimal': 0},
            'applicability': {},
            'avg_provisions': 0,
            'avg_relevance': 0,
        }
        
        total_provisions = 0
        total_relevance = 0
        
        for doc in documents:
            # Risk distribution
            risk_level = doc.get('risk_level', 'minimal')
            stats['risk_distribution'][risk_level] += 1
            
            # Applicability
            for app in doc.get('applicability', []):
                stats['applicability'][app] = stats['applicability'].get(app, 0) + 1
            
            # Averages
            total_provisions += doc.get('legal_provisions', {}).get('provision_count', 0)
            total_relevance += doc.get('relevance_score', 0)
        
        stats['avg_provisions'] = total_provisions / len(documents)
        stats['avg_relevance'] = total_relevance / len(documents)
        
        return stats
