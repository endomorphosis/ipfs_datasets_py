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

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

# Note: Native implementation should be imported directly:
# from ipfs_datasets_py.logic.CEC.native import DCECContainer, TheoremProver, etc.
#
# This package intentionally avoids importing optional/heavy wrappers at import time.
# Many wrappers rely on optional dependencies and/or decorators that emit warnings
# during import. Use attribute access (or explicit submodule imports) to load them.

if TYPE_CHECKING:
    from .cec_framework import CECFramework, FrameworkConfig, ReasoningMode, ReasoningTask
    from .dcec_wrapper import DCECLibraryWrapper, DCECStatement
    from .talos_wrapper import TalosWrapper, ProofAttempt, ProofResult
    from .eng_dcec_wrapper import EngDCECWrapper, ConversionResult
    from .shadow_prover_wrapper import ShadowProverWrapper, ProofTask, ProverStatus

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


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Framework
    "CECFramework": (".cec_framework", "CECFramework"),
    "FrameworkConfig": (".cec_framework", "FrameworkConfig"),
    "ReasoningMode": (".cec_framework", "ReasoningMode"),
    "ReasoningTask": (".cec_framework", "ReasoningTask"),
    # DCEC Library
    "DCECLibraryWrapper": (".dcec_wrapper", "DCECLibraryWrapper"),
    "DCECStatement": (".dcec_wrapper", "DCECStatement"),
    # Talos
    "TalosWrapper": (".talos_wrapper", "TalosWrapper"),
    "ProofAttempt": (".talos_wrapper", "ProofAttempt"),
    "ProofResult": (".talos_wrapper", "ProofResult"),
    # Eng-DCEC
    "EngDCECWrapper": (".eng_dcec_wrapper", "EngDCECWrapper"),
    "ConversionResult": (".eng_dcec_wrapper", "ConversionResult"),
    # ShadowProver
    "ShadowProverWrapper": (".shadow_prover_wrapper", "ShadowProverWrapper"),
    "ProofTask": (".shadow_prover_wrapper", "ProofTask"),
    "ProverStatus": (".shadow_prover_wrapper", "ProverStatus"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value