"""
Reasoning subsystem for logic module.

Provides core reasoning engines and proof execution.

Components:
- ProofExecutionEngine: Main proof execution engine
- DeontologicalReasoningEngine: Deontic reasoning engine
- LogicVerification: Logic verification system
"""

from .proof_execution_engine import ProofExecutionEngine
from .deontological_reasoning import DeontologicalReasoningEngine
from .logic_verification import LogicVerifier

__all__ = [
    'ProofExecutionEngine',
    'DeontologicalReasoningEngine',
    'LogicVerifier',
]
