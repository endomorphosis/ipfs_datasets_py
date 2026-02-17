"""
Base Classes for Extensible Complaint Analysis

These abstract base classes define the interface for extending the complaint
analysis system with new complaint types, keywords, and risk scoring logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class BaseLegalPatternExtractor(ABC):
    """
    Abstract base class for legal pattern extraction.
    
    Extend this class to add custom legal term patterns for new complaint types.
    """
    
    @abstractmethod
    def extract_provisions(self, text: str, context_chars: int = 200) -> Dict[str, Any]:
        """
        Extract legal provisions from text.
        
        Args:
            text: Text to analyze
            context_chars: Number of characters to include before/after match
            
        Returns:
            Dictionary with provisions, terms_found, provision_count, etc.
        """
        pass
    
    @abstractmethod
    def extract_citations(self, text: str) -> List[Dict[str, str]]:
        """
        Extract legal citations from text.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of found citations with metadata
        """
        pass
    
    @abstractmethod
    def categorize_complaint_type(self, text: str) -> List[str]:
        """
        Categorize the complaint based on content.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of applicable complaint categories
        """
        pass


class BaseKeywordRegistry(ABC):
    """
    Abstract base class for keyword registry.
    
    Extend this class to implement custom keyword management for different
    complaint types or domains.
    """
    
    @abstractmethod
    def register_keywords(self, category: str, keywords: List[str], 
                         complaint_type: Optional[str] = None) -> None:
        """
        Register keywords for a category.
        
        Args:
            category: Category name (e.g., 'complaint', 'evidence', 'legal')
            keywords: List of keywords to register
            complaint_type: Optional complaint type to scope keywords to
        """
        pass
    
    @abstractmethod
    def get_keywords(self, category: str, 
                     complaint_type: Optional[str] = None) -> List[str]:
        """
        Get keywords for a category.
        
        Args:
            category: Category name
            complaint_type: Optional complaint type to filter by
            
        Returns:
            List of keywords
        """
        pass
    
    @abstractmethod
    def get_all_categories(self, complaint_type: Optional[str] = None) -> List[str]:
        """
        Get all registered categories.
        
        Args:
            complaint_type: Optional complaint type to filter by
            
        Returns:
            List of category names
        """
        pass


class BaseRiskScorer(ABC):
    """
    Abstract base class for risk scoring.
    
    Extend this class to implement custom risk scoring logic for different
    complaint types or risk models.
    """
    
    @abstractmethod
    def calculate_risk(self, text: str, 
                      legal_provisions: Optional[List[Dict]] = None,
                      **kwargs) -> Dict[str, Any]:
        """
        Calculate risk score for a complaint.
        
        Args:
            text: Document text to analyze
            legal_provisions: Optional pre-extracted legal provisions
            **kwargs: Additional parameters for risk calculation
            
        Returns:
            Dictionary containing:
            - score: Risk score (numeric)
            - level: Risk level name
            - factors: List of contributing factors
            - recommendations: Suggested actions
        """
        pass
    
    @abstractmethod
    def get_risk_levels(self) -> List[str]:
        """
        Get available risk levels.
        
        Returns:
            List of risk level names (e.g., ['minimal', 'low', 'medium', 'high'])
        """
        pass
    
    @abstractmethod
    def is_actionable(self, text: str, threshold: float = 0.5) -> bool:
        """
        Determine if complaint is actionable.
        
        Args:
            text: Document text
            threshold: Minimum score threshold
            
        Returns:
            True if actionable
        """
        pass
