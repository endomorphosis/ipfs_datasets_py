"""
Shared components for legal search and complaint analysis.

This module contains components that are used by both:
- Brave Legal Search system (query_processor, search_term_generator)
- Complaint Analysis system (analyzer, indexer, risk_scoring)

Components extracted from complaint_analysis for reusability:
- keywords.py: Keyword registry and management
- legal_patterns.py: Pattern extraction and matching
- base.py: Abstract base classes and interfaces
- complaint_types.py: Complaint type definitions and registry

Usage:
    from ipfs_datasets_py.processors.legal_scrapers.common import (
        get_keywords,
        LegalPatternExtractor,
        BaseComplaintAnalyzer,
        get_registered_types
    )
"""

# Import all shared components for easy access
from .keywords import (
    COMPLAINT_KEYWORDS,
    register_keywords,
    register_legal_terms,
    get_keywords,
    get_type_specific_keywords,
)

from .legal_patterns import (
    LegalPatternExtractor,
    ComplaintLegalPatternExtractor,
    extract_legal_patterns,
    extract_complaint_patterns,
)

from .base import (
    BaseComplaintAnalyzer,
    BaseRiskScorer,
    BaseComplaintIndexer,
)

from .complaint_types import (
    ComplaintType,
    register_complaint_type,
    get_registered_types,
    get_complaint_type,
)

__all__ = [
    # Keywords
    'COMPLAINT_KEYWORDS',
    'register_keywords',
    'register_legal_terms',
    'get_keywords',
    'get_type_specific_keywords',
    # Legal Patterns
    'LegalPatternExtractor',
    'ComplaintLegalPatternExtractor',
    'extract_legal_patterns',
    'extract_complaint_patterns',
    # Base Classes
    'BaseComplaintAnalyzer',
    'BaseRiskScorer',
    'BaseComplaintIndexer',
    # Complaint Types
    'ComplaintType',
    'register_complaint_type',
    'get_registered_types',
    'get_complaint_type',
]
