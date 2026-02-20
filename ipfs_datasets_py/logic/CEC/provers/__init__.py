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
    formula_to_tptp,
    create_tptp_problem,
)

from .vampire_adapter import (
    VampireAdapter,
    VampireProofResult,
)

from .e_prover_adapter import (
    EProverAdapter,
    EProverProofResult,
)

from .prover_manager import (
    ProverManager,
    ProverStrategy,
    ProverConfig,
    ProverType,
    UnifiedProofResult,
)

# Backward-compat aliases
VampireResult = VampireProofResult
EProverResult = EProverProofResult
ProverResult = UnifiedProofResult


class TPTPFormula:
    """Wrapper for a TPTP-formatted formula string."""

    def __init__(self, content: str):
        self.content = content

    def __str__(self) -> str:
        return self.content


class TPTPConverter:
    """OOP wrapper around formula_to_tptp / create_tptp_problem utilities."""

    @staticmethod
    def convert(formula, role: str = "conjecture", name: str = "formula") -> TPTPFormula:
        """Convert a CEC formula to TPTP format."""
        return TPTPFormula(formula_to_tptp(formula, role=role, name=name))

    @staticmethod
    def create_problem(axioms, conjecture, problem_name: str = "problem") -> str:
        """Create a complete TPTP problem string."""
        return create_tptp_problem(axioms, conjecture, problem_name=problem_name)


__all__ = [
    # Z3
    'Z3Adapter',
    'ProofStatus',
    'Z3ProofResult',
    # TPTP
    'TPTPConverter',
    'TPTPFormula',
    'formula_to_tptp',
    'create_tptp_problem',
    # Vampire
    'VampireAdapter',
    'VampireProofResult',
    'VampireResult',  # compat alias
    # E Prover
    'EProverAdapter',
    'EProverProofResult',
    'EProverResult',  # compat alias
    # Manager
    'ProverManager',
    'ProverStrategy',
    'ProverConfig',
    'ProverType',
    'UnifiedProofResult',
    'ProverResult',  # compat alias
]
