"""
Domain-specific integrations for logic module.

Provides domain-specific tools for legal, medical, and contract domains.

Components:
- Legal: Domain knowledge, symbolic analysis, bulk processing
- Medical: Theorem proving framework
- Contracts: Symbolic contract verification
- Deontic: Query engines and temporal APIs
- Document: Consistency checking
"""

# Only import the classes that actually exist
try:
    from .legal_domain_knowledge import LegalDomainKnowledge
except ImportError:
    LegalDomainKnowledge = None

try:
    from .legal_symbolic_analyzer import LegalSymbolicAnalyzer
except ImportError:
    LegalSymbolicAnalyzer = None

try:
    from .deontic_query_engine import DeonticQueryEngine
except ImportError:
    DeonticQueryEngine = None

try:
    from .temporal_deontic_api import TemporalDeonticAPI
except ImportError:
    TemporalDeonticAPI = None

try:
    from .document_consistency_checker import DocumentConsistencyChecker
except ImportError:
    DocumentConsistencyChecker = None

__all__ = [
    'LegalDomainKnowledge',
    'LegalSymbolicAnalyzer',
    'DeonticQueryEngine',
    'TemporalDeonticAPI',
    'DocumentConsistencyChecker',
]
