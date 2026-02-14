"""
Reasoning subsystem for logic module.

Provides core reasoning engines and proof execution.

Components:
- ProofExecutionEngine: Main proof execution engine
- DeontologicalReasoning: Deontic reasoning engine
- LogicVerification: Logic verification system
"""

from .proof_execution_engine import ProofExecutionEngine
from .deontological_reasoning import DeontologicalReasoning
from .logic_verification import LogicVerification

__all__ = [
    'ProofExecutionEngine',
    'DeontologicalReasoning',
    'LogicVerification',
]
