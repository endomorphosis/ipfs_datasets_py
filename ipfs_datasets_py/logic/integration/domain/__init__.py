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

from .legal_domain_knowledge import LegalDomainKnowledge
from .legal_symbolic_analyzer import LegalSymbolicAnalyzer
from .medical_theorem_framework import MedicalTheoremFramework
from .symbolic_contracts import SymbolicContracts
from .document_consistency_checker import DocumentConsistencyChecker
from .deontic_query_engine import DeonticQueryEngine
from .temporal_deontic_api import TemporalDeonticAPI

__all__ = [
    'LegalDomainKnowledge',
    'LegalSymbolicAnalyzer',
    'MedicalTheoremFramework',
    'SymbolicContracts',
    'DocumentConsistencyChecker',
    'DeonticQueryEngine',
    'TemporalDeonticAPI',
]
