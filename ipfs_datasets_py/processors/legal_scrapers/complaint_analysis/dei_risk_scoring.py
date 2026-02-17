"""
DEI Risk Scoring Module

Enhanced risk scoring specifically for DEI (Diversity, Equity, Inclusion) policy analysis.
Integrates algorithms from HACC's index_and_tag.py for detecting potentially
problematic DEI requirements in policies and contracts.

Risk Scoring Methodology (0-3 scale):
- 0: No evidence of DEI requirements (compliant/no issue)
- 1: Possible DEI references (needs review)
- 2: Probable DEI requirements with binding language (likely issue)
- 3: Clear DEI mandates with enforcement language (definite issue)
"""

from typing import Dict, List, Optional, Any
from .keywords import get_keywords


class DEIRiskScorer:
    """
    Calculate risk scores for DEI policy compliance issues.
    
    Based on HACC's document indexing and tagging methodology, this scorer
    identifies potentially problematic DEI language in policies, contracts,
    and regulations that may create legal or compliance risks.
    
    Example:
        >>> scorer = DEIRiskScorer()
        >>> risk = scorer.calculate_risk(policy_text)
        >>> print(f"Risk Level: {risk['level']} ({risk['score']}/3)")
        >>> print(f"Issues Found: {risk['issues']}")
    """
    
    def __init__(self):
        """Initialize the DEI risk scorer with keyword sets."""
        self.dei_keywords = get_keywords('complaint', complaint_type='dei')
        self.proxy_keywords = get_keywords('dei_proxy', complaint_type='dei')
        self.binding_keywords = get_keywords('binding', complaint_type='dei')
    
    def calculate_risk(self, text: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Calculate comprehensive DEI risk score for a document.
        
        This implements the HACC algorithm:
        - Count DEI keywords (direct references to diversity, equity, inclusion)
        - Count proxy keywords (euphemisms like "cultural competence", "lived experience")
        - Count binding indicators ("shall", "required", "mandatory", "policy")
        - Apply scoring rubric based on keyword combinations
        
        Args:
            text: Document text to analyze
            metadata: Optional metadata about the document
            
        Returns:
            Dictionary containing:
            - score: Risk score (0-3)
            - level: Risk level name ('compliant', 'low', 'medium', 'high')
            - dei_count: Number of direct DEI keyword matches
            - proxy_count: Number of proxy keyword matches
            - binding_count: Number of binding indicator matches
            - issues: List of specific issues identified
            - recommendations: Suggested actions
            - flagged_keywords: Keywords that triggered the score
        """
        # Count keyword occurrences
        dei_count = self._count_keywords(text, self.dei_keywords)
        proxy_count = self._count_keywords(text, self.proxy_keywords)
        binding_count = self._count_keywords(text, self.binding_keywords)
        
        # Track which keywords were found
        flagged_dei = self._extract_keywords(text, self.dei_keywords)
        flagged_proxy = self._extract_keywords(text, self.proxy_keywords)
        flagged_binding = self._extract_keywords(text, self.binding_keywords)
        
        # Calculate risk score using HACC algorithm
        score = self._calculate_score(dei_count, proxy_count, binding_count)
        
        # Determine risk level
        level_names = {
            0: 'compliant',
            1: 'low',
            2: 'medium',
            3: 'high'
        }
        level = level_names[score]
        
        # Identify specific issues
        issues = self._identify_issues(dei_count, proxy_count, binding_count, 
                                       flagged_dei, flagged_proxy, flagged_binding)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(score, issues)
        
        return {
            'score': score,
            'level': level,
            'dei_count': dei_count,
            'proxy_count': proxy_count,
            'binding_count': binding_count,
            'issues': issues,
            'recommendations': recommendations,
            'flagged_keywords': {
                'dei': flagged_dei[:10],  # Limit to first 10
                'proxy': flagged_proxy[:10],
                'binding': flagged_binding[:10]
            },
            'metadata': metadata or {}
        }
    
    def _calculate_score(self, dei_count: int, proxy_count: int, binding_count: int) -> int:
        """
        Calculate risk score based on HACC algorithm.
        
        Scoring rubric from HACC's index_and_tag.py:
        - Score 3: DEI + proxy + binding (clear issue)
        - Score 2: (DEI OR proxy) + binding (probable issue)
        - Score 1: DEI OR proxy (possible issue)
        - Score 0: No DEI/proxy language (compliant)
        """
        if dei_count > 0 and binding_count > 0 and proxy_count > 0:
            return 3  # Clear issue: Direct DEI + proxies + binding language
        elif (dei_count > 0 or proxy_count > 0) and binding_count > 0:
            return 2  # Probable issue: DEI language with binding indicators
        elif dei_count > 0 or proxy_count > 0:
            return 1  # Possible issue: DEI language but weak enforcement
        return 0  # Compliant: No problematic DEI language
    
    def _count_keywords(self, text: str, keywords: List[str]) -> int:
        """Count occurrences of keywords in text (case-insensitive)."""
        text_lower = text.lower()
        count = 0
        for keyword in keywords:
            if keyword.lower() in text_lower:
                count += 1
        return count
    
    def _extract_keywords(self, text: str, keywords: List[str]) -> List[str]:
        """Extract keywords that are found in text."""
        found = []
        text_lower = text.lower()
        for keyword in keywords:
            if keyword.lower() in text_lower:
                found.append(keyword)
        return list(set(found))  # deduplicate
    
    def _identify_issues(self, dei_count: int, proxy_count: int, binding_count: int,
                        flagged_dei: List[str], flagged_proxy: List[str], 
                        flagged_binding: List[str]) -> List[str]:
        """Identify specific issues based on keywords found."""
        issues = []
        
        if dei_count > 0 and binding_count > 0:
            issues.append(f"Document contains {dei_count} direct DEI references with binding language")
            if flagged_dei:
                issues.append(f"DEI terms found: {', '.join(flagged_dei[:5])}")
        
        if proxy_count > 0 and binding_count > 0:
            issues.append(f"Document contains {proxy_count} DEI proxy/euphemism terms with binding language")
            if flagged_proxy:
                issues.append(f"Proxy terms found: {', '.join(flagged_proxy[:5])}")
        
        if binding_count > 0:
            issues.append(f"Document contains {binding_count} binding/mandatory language indicators")
            if flagged_binding:
                issues.append(f"Binding terms: {', '.join(flagged_binding[:5])}")
        
        if dei_count > 0 or proxy_count > 0:
            if binding_count == 0:
                issues.append("DEI language present but lacks clear binding indicators")
        
        if not issues:
            issues.append("No problematic DEI language detected")
        
        return issues
    
    def _generate_recommendations(self, score: int, issues: List[str]) -> List[str]:
        """Generate action recommendations based on risk score."""
        recommendations = []
        
        if score == 3:
            recommendations.extend([
                'URGENT: Legal review required - clear DEI requirements detected',
                'Document contains mandatory DEI language that may violate neutrality principles',
                'Consult with legal counsel regarding potential discrimination issues',
                'Review all related policies and contracts for similar language',
                'Consider requesting policy amendment or exemption',
                'Document all instances for potential challenge',
            ])
        elif score == 2:
            recommendations.extend([
                'HIGH PRIORITY: Detailed legal analysis recommended',
                'Policy contains DEI language with binding indicators',
                'Review applicability to your organization',
                'Assess whether requirements can be interpreted neutrally',
                'Request clarification on enforcement and compliance expectations',
                'Monitor for enforcement actions',
            ])
        elif score == 1:
            recommendations.extend([
                'MEDIUM PRIORITY: Monitor and document',
                'DEI language present but enforcement unclear',
                'Track policy developments and implementation',
                'Document any requests related to DEI compliance',
                'Maintain awareness of similar policies',
            ])
        else:
            recommendations.extend([
                'No immediate action required',
                'Policy appears compliant with neutrality principles',
                'Continue monitoring for policy changes',
            ])
        
        return recommendations
    
    def tag_applicability(self, text: str) -> List[str]:
        """
        Tag document with applicability areas (hiring, procurement, etc.).
        
        Based on HACC's applicability tagging from index_and_tag.py.
        """
        from .keywords import get_keywords
        
        applicability_areas = [
            'housing', 'employment', 'public_accommodation',
            'lending', 'education', 'government_services',
            'procurement', 'training', 'community_engagement'
        ]
        
        tags = []
        text_lower = text.lower()
        
        for area in applicability_areas:
            area_keywords = get_keywords(f'applicability_{area}', complaint_type='dei')
            # Check if any keywords for this area are present
            for keyword in area_keywords:
                if keyword.lower() in text_lower:
                    tags.append(area)
                    break  # Only tag once per area
        
        return tags
    
    def is_problematic(self, text: str, threshold: int = 2) -> bool:
        """
        Determine if document contains problematic DEI requirements.
        
        Args:
            text: Document text
            threshold: Minimum risk score to be considered problematic (default: 2)
            
        Returns:
            True if risk score meets or exceeds threshold
        """
        risk = self.calculate_risk(text)
        return risk['score'] >= threshold
