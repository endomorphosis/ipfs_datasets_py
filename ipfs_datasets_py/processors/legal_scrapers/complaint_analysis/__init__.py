"""
Complaint Analysis Module

A flexible, extensible framework for analyzing legal complaints across different
domains (housing, employment, civil rights, consumer protection, etc.).

This module provides:
1. Extensible legal term pattern extraction
2. Configurable keyword taxonomies for different complaint types
3. Pluggable risk scoring algorithms
4. Hybrid document indexing (vector + keyword)

The framework is designed to be extended with new complaint types by:
- Registering new keyword sets
- Adding new legal pattern categories
- Implementing custom risk scorers

Example:
    >>> from complaint_analysis import ComplaintAnalyzer
    >>> analyzer = ComplaintAnalyzer(complaint_type='housing')
    >>> result = analyzer.analyze(document_text)
    >>> print(f"Risk: {result['risk_level']}, Categories: {result['categories']}")

Note:
    Shared components (keywords, legal_patterns, base, complaint_types) have been
    extracted to legal_scrapers/common/ for reuse by Brave Legal Search.
    They are re-exported here for full backward compatibility.
"""

# Import shared components from common/ (re-exported for backward compatibility)
from ..common import (
    get_keywords,
    get_type_specific_keywords,
    register_keywords,
    COMPLAINT_KEYWORDS,
    LegalPatternExtractor,
    BaseComplaintAnalyzer as BaseKeywordRegistry,  # Alias for backward compat
    BaseRiskScorer,
    get_registered_types,
)

# Import local implementations that wrap or use common components
from .base import (
    BaseLegalPatternExtractor,
)

# Re-import to maintain existing import paths
from .legal_patterns import (
    LEGAL_TERMS_REGISTRY, 
    COMPLAINT_LEGAL_TERMS,
    register_legal_terms,
    get_legal_terms
)

from .keywords import (
    KeywordRegistry,
    EVIDENCE_KEYWORDS,
    LEGAL_AUTHORITY_KEYWORDS,
    APPLICABILITY_KEYWORDS
)
from .risk_scoring import ComplaintRiskScorer
from .dei_risk_scoring import DEIRiskScorer
from .dei_provision_extractor import DEIProvisionExtractor
from .dei_report_generator import DEIReportGenerator
from .indexer import HybridDocumentIndexer
from .complaint_types import (
    register_housing_complaint,
    register_employment_complaint,
    register_civil_rights_complaint,
    register_consumer_complaint,
    register_healthcare_complaint,
    register_free_speech_complaint,
    register_immigration_complaint,
    register_family_law_complaint,
    register_criminal_defense_complaint,
    register_tax_law_complaint,
    register_intellectual_property_complaint,
    register_environmental_law_complaint,
    register_dei_complaint,
    get_registered_types
)
from .analyzer import ComplaintAnalyzer
from .seed_generator import SeedGenerator, SeedComplaintTemplate
from .decision_trees import (
    DecisionTreeGenerator,
    DecisionTree,
    QuestionNode
)
from .prompt_templates import (
    PromptTemplate,
    PromptLibrary,
    ReturnFormat
)
from .response_parsers import (
    BaseResponseParser,
    JSONResponseParser,
    StructuredTextParser,
    EntityParser,
    RelationshipParser,
    QuestionParser,
    ClaimParser,
    StateFileIngester,
    ResponseParserFactory,
    ParsedResponse
)

# Aliases for backward compatibility
RiskScorer = ComplaintRiskScorer
ComplaintLegalPatternExtractor = LegalPatternExtractor  # Backward compatibility alias

__all__ = [
    # Base classes for extension
    'BaseLegalPatternExtractor',
    'BaseKeywordRegistry',
    'BaseRiskScorer',
    
    # Main classes
    'LegalPatternExtractor',
    'ComplaintLegalPatternExtractor',  # Backward compatibility alias
    'KeywordRegistry',
    'ComplaintRiskScorer',
    'DEIRiskScorer',  # DEI-specific risk scorer
    'DEIProvisionExtractor',  # DEI provision extractor
    'DEIReportGenerator',  # DEI report generator
    'RiskScorer',  # Alias
    'HybridDocumentIndexer',
    'ComplaintAnalyzer',
    
    # Seed generation and decision trees
    'SeedGenerator',
    'SeedComplaintTemplate',
    'DecisionTreeGenerator',
    'DecisionTree',
    'QuestionNode',
    
    # Prompt engineering
    'PromptTemplate',
    'PromptLibrary',
    'ReturnFormat',
    
    # Response parsing
    'BaseResponseParser',
    'JSONResponseParser',
    'StructuredTextParser',
    'EntityParser',
    'RelationshipParser',
    'QuestionParser',
    'ClaimParser',
    'StateFileIngester',
    'ResponseParserFactory',
    'ParsedResponse',
    
    # Functions
    'get_keywords',
    'get_type_specific_keywords',
    'register_keywords',
    'register_legal_terms',
    'get_legal_terms',
    
    # Default keyword sets
    'COMPLAINT_KEYWORDS',
    'EVIDENCE_KEYWORDS',
    'LEGAL_AUTHORITY_KEYWORDS',
    'APPLICABILITY_KEYWORDS',
    
    # Registry
    'LEGAL_TERMS_REGISTRY',
    'COMPLAINT_LEGAL_TERMS',
    
    # Registration functions
    'register_housing_complaint',
    'register_employment_complaint',
    'register_civil_rights_complaint',
    'register_consumer_complaint',
    'register_healthcare_complaint',
    'register_free_speech_complaint',
    'register_immigration_complaint',
    'register_family_law_complaint',
    'register_criminal_defense_complaint',
    'register_tax_law_complaint',
    'register_intellectual_property_complaint',
    'register_environmental_law_complaint',
    'register_dei_complaint',
    'get_registered_types',
]

__version__ = '2.0.0'
