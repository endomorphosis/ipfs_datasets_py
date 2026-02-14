"""
Bridges subsystem for logic module.

Provides bridge implementations between different theorem proving systems.

Components:
- BaseProverBridge: Base class for prover bridges
- SymbolicFOLBridge: Bridge to SymbolicAI FOL
- TDFOLCECBridge: Bridge to TDFOL-CEC integration
- TDFOLGrammarBridge: Bridge to TDFOL grammar engine
- TDFOLShadowProverBridge: Bridge to TDFOL-ShadowProver
- ExternalProvers: External prover integrations
- ProverInstaller: Prover installation utilities
"""

from .base_prover_bridge import BaseProverBridge
from .symbolic_fol_bridge import SymbolicFOLBridge
from .tdfol_cec_bridge import TDFOLCECBridge
from .tdfol_grammar_bridge import TDFOLGrammarBridge
from .tdfol_shadowprover_bridge import TDFOLShadowProverBridge

__all__ = [
    'BaseProverBridge',
    'SymbolicFOLBridge',
    'TDFOLCECBridge',
    'TDFOLGrammarBridge',
    'TDFOLShadowProverBridge',
]
