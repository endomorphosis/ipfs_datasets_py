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

from typing import List, Optional

__version__ = "1.0.0"

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

# Prover router
try:
    from .prover_router import ProverRouter
except ImportError:
    ProverRouter = None


def get_available_provers() -> List[str]:
    """Get list of available external provers.
    
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
    return provers


def check_prover_availability(prover_name: str) -> bool:
    """Check if a specific prover is available.
    
    Args:
        prover_name: Name of the prover ("Z3", "CVC5", "Lean", "Coq")
        
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
    return False


__all__ = [
    # Core interfaces
    "Z3ProverBridge",
    "CVC5ProverBridge",
    "SMTProverInterface",
    "LeanProverBridge",
    "CoqProverBridge",
    "ProverRouter",
    # Availability flags
    "Z3_AVAILABLE",
    "CVC5_AVAILABLE",
    "LEAN_AVAILABLE",
    "COQ_AVAILABLE",
    # Utility functions
    "get_available_provers",
    "check_prover_availability",
]
