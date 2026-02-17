"""
Unified Complaint Analyzer

Provides a high-level interface for analyzing complaints with all components.
"""

from typing import Dict, Optional, Any
from .legal_patterns import LegalPatternExtractor
from .risk_scoring import ComplaintRiskScorer
from .keywords import get_keywords


class ComplaintAnalyzer:
    """
    Unified analyzer combining all complaint analysis components.
    
    Example:
        >>> analyzer = ComplaintAnalyzer(complaint_type='housing')
        >>> result = analyzer.analyze(document_text)
        >>> print(f"Risk: {result['risk_level']}")
    """
    
    def __init__(self, complaint_type: Optional[str] = None):
        """
        Initialize the analyzer.
        
        Args:
            complaint_type: Optional complaint type for specialized analysis
        """
        self.complaint_type = complaint_type
        self.legal_extractor = LegalPatternExtractor()
        self.risk_scorer = ComplaintRiskScorer()
    
    def analyze(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Perform complete analysis on complaint text.
        
        Args:
            text: Complaint text to analyze
            metadata: Optional metadata
            
        Returns:
            Complete analysis results
        """
        # Extract legal provisions
        provisions = self.legal_extractor.extract_provisions(text)
        citations = self.legal_extractor.extract_citations(text)
        categories = self.legal_extractor.categorize_complaint_type(text)
        
        # Calculate risk
        risk = self.risk_scorer.calculate_risk(text, provisions['provisions'])
        
        # Extract keywords using global registry
        complaint_keywords = get_keywords('complaint', self.complaint_type)
        found_keywords = [kw for kw in complaint_keywords if kw.lower() in text.lower()]
        
        return {
            'legal_provisions': provisions,
            'citations': citations,
            'categories': categories,
            'risk_score': risk['score'],
            'risk_level': risk['level'],
            'risk_factors': risk['factors'],
            'recommendations': risk['recommendations'],
            'keywords_found': found_keywords[:20],  # Top 20
            'metadata': metadata or {}
        }
