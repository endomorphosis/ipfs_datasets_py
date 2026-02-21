"""
CEC External Provers Module.

This module provides interfaces to external theorem provers including:
- Z3: SMT solver with strong support for theories
- Vampire: ATP for first-order logic with equality
- E Prover: Efficient ATP for first-order logic
- TPTP utilities for format conversion
- Unified prover manager with automatic selection

Key Components:
- Z3Adapter: Interface to Z3 SMT solver
- VampireAdapter: Interface to Vampire ATP
- EProverAdapter: Interface to E Prover
- TPTPConverter: Convert DCEC to TPTP format
- ProverManager: Unified management and automatic selection
- ProverStrategy: Strategy enumeration for prover selection

Usage:
    from ipfs_datasets_py.logic.CEC.provers import (
        ProverManager, ProverStrategy
    )
    
    # Automatic prover selection
    manager = ProverManager()
    result = manager.prove(
        formula=my_formula,
        axioms=[axiom1, axiom2],
        strategy=ProverStrategy.AUTO
    )
    
    # Or use specific prover
    from ipfs_datasets_py.logic.CEC.provers import Z3Adapter
    
    z3 = Z3Adapter()
    result = z3.prove(formula, axioms)
"""

from .z3_adapter import (
    Z3Adapter,
    ProofStatus,
    Z3ProofResult,
)

from .tptp_utils import (
    TPTPConverter,
    TPTPFormula,
)

from .vampire_adapter import (
    VampireAdapter,
    VampireProofResult as VampireResult,
)

from .e_prover_adapter import (
    EProverAdapter,
    EProverProofResult as EProverResult,
)

from .prover_manager import (
    ProverManager,
    ProverStrategy,
    UnifiedProofResult as ProverResult,
)

__all__ = [
    # Z3
    'Z3Adapter',
    'ProofStatus',
    'Z3ProofResult',
    # TPTP
    'TPTPConverter',
    'TPTPFormula',
    # Vampire
    'VampireAdapter',
    'VampireResult',
    # E Prover
    'EProverAdapter',
    'EProverResult',
    # Manager
    'ProverManager',
    'ProverStrategy',
    'ProverResult',
]
