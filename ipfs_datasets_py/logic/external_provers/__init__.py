"""
External Theorem Prover Integration for TDFOL

This module integrates world-class external theorem provers with the neurosymbolic
reasoning system, including:

- **Z3**: Microsoft's SMT solver (industrial-strength SAT/SMT solving)
- **CVC5**: Stanford's SMT solver (excellent quantifier handling)
- **Lean**: Microsoft's interactive theorem prover (dependent type theory)
- **Coq**: INRIA's proof assistant (Calculus of Inductive Constructions)

The integration provides:
1. Formula conversion (TDFOL → prover-specific formats)
2. Unified prover interface
3. Automatic prover selection
4. Parallel proving (try multiple provers simultaneously)
5. Result normalization and aggregation

Usage:
    >>> from ipfs_datasets_py.logic.external_provers import Z3ProverBridge
    >>> prover = Z3ProverBridge()
    >>> result = prover.prove(formula)

    >>> from ipfs_datasets_py.logic.external_provers import ProverRouter
    >>> router = ProverRouter(enable_z3=True, enable_cvc5=True)
    >>> result = router.prove(formula, strategy='auto')
"""

import importlib
from typing import List, Optional

from .deterministic_router import (
    DETERMINISTIC_PROVER_ROUTE_SCHEMA_VERSION,
    select_deterministic_prover_route,
)

__version__ = "1.0.0"

try:
    from .lazy_installer import (
        ProverInstallEvent,
        ProgressCallback,
        default_first_use_prover_portfolio,
        ensure_default_prover_portfolio,
        ensure_prover_executable,
        ensure_managed_ergoai_if_missing,
        find_executable,
        lazy_install_prover,
        lazy_installs_enabled,
        prover_lazy_install_enabled,
    )
except ImportError:
    ProverInstallEvent = None
    ProgressCallback = None
    default_first_use_prover_portfolio = None
    ensure_default_prover_portfolio = None
    ensure_prover_executable = None
    ensure_managed_ergoai_if_missing = None
    find_executable = None
    lazy_install_prover = None
    lazy_installs_enabled = None
    prover_lazy_install_enabled = None

# Try to import SMT solvers (optional dependencies)
try:
    from .smt.z3_prover_bridge import Z3ProverBridge, Z3_AVAILABLE
except ImportError:
    Z3ProverBridge = None
    Z3_AVAILABLE = False

try:
    from .smt.cvc5_prover_bridge import CVC5ProverBridge, CVC5_AVAILABLE
except ImportError:
    CVC5ProverBridge = None
    CVC5_AVAILABLE = False

try:
    from .smt.smt_prover_interface import SMTProverInterface
except ImportError:
    SMTProverInterface = None

# Try to import interactive provers (require external binaries)
try:
    from .interactive.lean_prover_bridge import LeanProverBridge, LEAN_AVAILABLE
except ImportError:
    LeanProverBridge = None
    LEAN_AVAILABLE = False

try:
    from .interactive.coq_prover_bridge import CoqProverBridge, COQ_AVAILABLE
except ImportError:
    CoqProverBridge = None
    COQ_AVAILABLE = False

# Native prover imports must not initialize optional LLM configuration. Resolve
# these compatibility exports only when callers explicitly request them.
_NEURAL_EXPORTS = frozenset({"SymbolicAIProverBridge", "SYMBOLICAI_AVAILABLE", "NeuralProofResult"})


def _load_neural_exports() -> None:
    if _NEURAL_EXPORTS.issubset(globals()):
        return
    try:
        module = importlib.import_module(".neural.symbolicai_prover_bridge", __name__)
    except ImportError:
        exports = {"SymbolicAIProverBridge": None, "SYMBOLICAI_AVAILABLE": False,
                   "NeuralProofResult": None}
    else:
        exports = {name: getattr(module, name) for name in _NEURAL_EXPORTS}
    globals().update(exports)


def __getattr__(name: str):
    if name not in _NEURAL_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    _load_neural_exports()
    return globals()[name]


def __dir__():
    return sorted(set(globals()) | _NEURAL_EXPORTS)

# Prover router
try:
    from .prover_router import ProverRouter
except ImportError:
    ProverRouter = None

# Formula analyzer
try:
    from .formula_analyzer import FormulaAnalyzer, FormulaAnalysis, FormulaType, FormulaComplexity
except ImportError:
    FormulaAnalyzer = None
    FormulaAnalysis = None
    FormulaType = None
    FormulaComplexity = None


def get_available_provers() -> List[str]:
    """Get list of available external provers.

    Requesting the complete list also resolves the optional neural bridge.
    Importing this package or checking a native prover does not do so.

    Returns:
        List of prover names that are available on this system.
    """
    provers = []
    if Z3_AVAILABLE:
        provers.append("Z3")
    if CVC5_AVAILABLE:
        provers.append("CVC5")
    if LEAN_AVAILABLE:
        provers.append("Lean")
    if COQ_AVAILABLE:
        provers.append("Coq")
    _load_neural_exports()
    if globals()["SYMBOLICAI_AVAILABLE"]:
        provers.append("SymbolicAI")
    return provers


def check_prover_availability(prover_name: str) -> bool:
    """Check if a specific prover is available.

    Args:
        prover_name: Name of the prover ("Z3", "CVC5", "Lean", "Coq", "SymbolicAI")

    Returns:
        True if the prover is available, False otherwise.
    """
    prover_name = prover_name.upper()
    if prover_name == "Z3":
        return Z3_AVAILABLE
    elif prover_name == "CVC5":
        return CVC5_AVAILABLE
    elif prover_name == "LEAN":
        return LEAN_AVAILABLE
    elif prover_name == "COQ":
        return COQ_AVAILABLE
    elif prover_name == "SYMBOLICAI":
        _load_neural_exports()
        return globals()["SYMBOLICAI_AVAILABLE"]
    return False


__all__ = [
    # Core interfaces
    "Z3ProverBridge",
    "CVC5ProverBridge",
    "SMTProverInterface",
    "LeanProverBridge",
    "CoqProverBridge",
    "SymbolicAIProverBridge",
    "ProverRouter",
    # Formula analysis
    "FormulaAnalyzer",
    "FormulaAnalysis",
    "FormulaType",
    "FormulaComplexity",
    # Result types
    "NeuralProofResult",
    # Availability flags
    "Z3_AVAILABLE",
    "CVC5_AVAILABLE",
    "LEAN_AVAILABLE",
    "COQ_AVAILABLE",
    "SYMBOLICAI_AVAILABLE",
    # Utility functions
    "get_available_provers",
    "check_prover_availability",
    "find_executable",
    "ensure_prover_executable",
    "ensure_managed_ergoai_if_missing",
    "ensure_default_prover_portfolio",
    "default_first_use_prover_portfolio",
    "lazy_install_prover",
    "lazy_installs_enabled",
    "prover_lazy_install_enabled",
    "ProverInstallEvent",
    "ProgressCallback",
    "DETERMINISTIC_PROVER_ROUTE_SCHEMA_VERSION",
    "select_deterministic_prover_route",
]
