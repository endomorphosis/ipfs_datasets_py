"""
Risk Scoring for Complaints

Adapted from HACC's report_generator.py risk scoring logic.
Calculates risk scores based on keyword presence and legal patterns.
"""

from typing import Dict, List, Optional, Any
from .keywords import get_keywords
from .legal_patterns import LegalPatternExtractor


class ComplaintRiskScorer:
    """
    Calculate risk scores for complaints based on content analysis.
    
    Risk levels:
    - 0: Minimal/No risk
    - 1: Low risk (possible issue, needs review)
    - 2: Medium risk (probable issue, requires action)
    - 3: High risk (clear issue, immediate action needed)
    
    Example:
        >>> scorer = ComplaintRiskScorer()
        >>> risk = scorer.calculate_risk(document_text, legal_provisions)
        >>> print(f"Risk Level: {risk['level']} ({risk['score']})")
    """
    
    def __init__(self):
        self.legal_extractor = LegalPatternExtractor()
    
    def calculate_risk(self, text: str, 
                      legal_provisions: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Calculate comprehensive risk score for a complaint document.
        
        Args:
            text: Document text to analyze
            legal_provisions: Optional pre-extracted legal provisions
            
        Returns:
            Dictionary containing:
            - score: Risk score (0-3)
            - level: Risk level name ('minimal', 'low', 'medium', 'high')
            - factors: List of contributing risk factors
            - recommendations: Suggested actions
        """
        if legal_provisions is None:
            extraction_result = self.legal_extractor.extract_provisions(text)
            legal_provisions = extraction_result['provisions']
        
        # Count different keyword types
        complaint_count = self._count_keywords(text, get_keywords('complaint'))
        binding_count = self._count_keywords(text, get_keywords('binding'))
        severity_high = self._count_keywords(text, get_keywords('severity_high'))
        severity_medium = self._count_keywords(text, get_keywords('severity_medium'))
        
        # Count legal provisions
        provision_count = len(legal_provisions)
        
        # Calculate base score
        score = 0
        factors = []
        
        # High risk indicators
        if severity_high > 0 and provision_count > 0 and binding_count > 0:
            score = 3
            factors.append('Severe legal violations with binding authority')
        elif complaint_count > 5 and binding_count > 2 and provision_count > 3:
            score = 3
            factors.append('Multiple complaint terms with enforceable provisions')
        
        # Medium risk indicators
        elif (complaint_count > 0 or severity_medium > 0) and binding_count > 0:
            score = 2
            factors.append('Complaint terms with binding language')
        elif provision_count > 5:
            score = 2
            factors.append('Multiple legal provisions identified')
        
        # Low risk indicators
        elif complaint_count > 0 or provision_count > 0:
            score = 1
            factors.append('Potential legal issues identified')
        
        # Risk level names
        level_names = {
            0: 'minimal',
            1: 'low',
            2: 'medium',
            3: 'high'
        }
        
        # Generate recommendations
        recommendations = self._generate_recommendations(score, factors)
        
        return {
            'score': score,
            'level': level_names[score],
            'factors': factors,
            'complaint_keywords': complaint_count,
            'binding_keywords': binding_count,
            'legal_provisions': provision_count,
            'severity_indicators': severity_high + severity_medium,
            'recommendations': recommendations
        }
    
    def _count_keywords(self, text: str, keywords: List[str]) -> int:
        """Count occurrences of keywords in text (case-insensitive)."""
        text_lower = text.lower()
        count = 0
        for keyword in keywords:
            if keyword.lower() in text_lower:
                count += 1
        return count
    
    def _generate_recommendations(self, score: int, factors: List[str]) -> List[str]:
        """Generate action recommendations based on risk score."""
        recommendations = []
        
        if score == 3:
            recommendations.extend([
                'Immediate legal review required',
                'Consult with attorney specializing in this area',
                'Gather all supporting evidence and documentation',
                'Consider filing formal complaint with appropriate agency',
                'Document all communications and interactions'
            ])
        elif score == 2:
            recommendations.extend([
                'Legal consultation recommended',
                'Collect additional evidence and documentation',
                'Review applicable laws and regulations',
                'Consider mediation or informal resolution',
                'Maintain detailed records of the situation'
            ])
        elif score == 1:
            recommendations.extend([
                'Monitor situation for escalation',
                'Document any new developments',
                'Research relevant legal protections',
                'Consider seeking informal resolution',
                'Keep records of all communications'
            ])
        else:
            recommendations.extend([
                'No immediate action required',
                'Continue monitoring if situation changes',
                'Maintain awareness of legal rights'
            ])
        
        return recommendations
    
    def categorize_severity(self, text: str) -> str:
        """
        Categorize the severity of the complaint.
        
        Args:
            text: Document text
            
        Returns:
            Severity category: 'high', 'medium', 'low', or 'minimal'
        """
        risk_result = self.calculate_risk(text)
        return risk_result['level']
    
    def is_actionable(self, text: str, threshold: int = 2) -> bool:
        """
        Determine if complaint is actionable (meets risk threshold).
        
        Args:
            text: Document text
            threshold: Minimum risk score (default: 2 for medium risk)
            
        Returns:
            True if risk score meets or exceeds threshold
        """
        risk_result = self.calculate_risk(text)
        return risk_result['score'] >= threshold
