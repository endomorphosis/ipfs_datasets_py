"""
Cognitive Event Calculus (CEC) Module

This module provides a unified neurosymbolic framework for Cognitive Event Calculus,
integrating theorem proving, natural language conversion, and formal reasoning.

Native Python 3 Implementation:
- native: Pure Python 3 implementation of CEC (recommended)
  Located in: ipfs_datasets_py.logic.CEC.native
  Features: 2-4x faster, zero dependencies, 418+ tests

Legacy Submodules:
- DCEC_Library: Deontic Cognitive Event Calculus logic system
- Talos: Theorem prover interface with SPASS
- Eng-DCEC: English to DCEC converter
- ShadowProver: Shadow theorem prover

Main Components:
- CECFramework: Unified high-level API
- Individual wrappers for each submodule
"""

# Note: Native implementation should be imported directly:
# from ipfs_datasets_py.logic.CEC.native import DCECContainer, TheoremProver, etc.

from .cec_framework import (
    CECFramework,
    FrameworkConfig,
    ReasoningMode,
    ReasoningTask
)

from .dcec_wrapper import (
    DCECLibraryWrapper,
    DCECStatement
)

from .talos_wrapper import (
    TalosWrapper,
    ProofAttempt,
    ProofResult
)

from .eng_dcec_wrapper import (
    EngDCECWrapper,
    ConversionResult
)

from .shadow_prover_wrapper import (
    ShadowProverWrapper,
    ProofTask,
    ProverStatus
)

__all__ = [
    # Framework
    "CECFramework",
    "FrameworkConfig",
    "ReasoningMode",
    "ReasoningTask",
    # DCEC Library
    "DCECLibraryWrapper",
    "DCECStatement",
    # Talos
    "TalosWrapper",
    "ProofAttempt",
    "ProofResult",
    # Eng-DCEC
    "EngDCECWrapper",
    "ConversionResult",
    # ShadowProver
    "ShadowProverWrapper",
    "ProofTask",
    "ProverStatus",
    # Native module available via: from ipfs_datasets_py.logic.CEC.native import ...
]