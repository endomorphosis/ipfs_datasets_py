"""
Proof Execution Engine Utilities

This module provides utility functions and helpers for the Proof
Execution Engine, including factory functions and convenience wrappers.

Extracted from proof_execution_engine.py to improve modularity.
"""

from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .proof_execution_engine import ProofExecutionEngine
    from .proof_execution_engine_types import ProofResult
    from ..converters.deontic_logic_core import DeonticFormula, DeonticRuleSet


def create_proof_engine(temp_dir: Optional[str] = None, timeout: int = 60) -> "ProofExecutionEngine":
    """
    Factory function to create a ProofExecutionEngine instance.
    
    This is the recommended way to create a ProofExecutionEngine,
    providing a clean API for engine creation with sensible defaults.
    
    Args:
        temp_dir: Optional temporary directory for proof files
        timeout: Timeout for proof execution in seconds (default: 60)
        
    Returns:
        ProofExecutionEngine instance ready for use
        
    Example:
        >>> engine = create_proof_engine(timeout=120)
        >>> # Use engine for proofs
    """
    from .proof_execution_engine import ProofExecutionEngine
    return ProofExecutionEngine(temp_dir=temp_dir, timeout=timeout)


def prove_formula(
    formula: "DeonticFormula", 
    prover: str = "z3", 
    timeout: int = 60,
    temp_dir: Optional[str] = None
) -> "ProofResult":
    """
    Quick proof of a single deontic formula.
    
    Creates a ProofExecutionEngine and proves the given formula using
    the specified prover.
    
    Args:
        formula: Deontic formula to prove
        prover: Theorem prover to use (default: "z3")
        timeout: Timeout in seconds (default: 60)
        temp_dir: Optional temporary directory
        
    Returns:
        ProofResult with execution details
        
    Example:
        >>> from ipfs_datasets_py.logic.integration.deontic_logic_core import create_obligation
        >>> formula = create_obligation("pay_taxes", "citizen")
        >>> result = prove_formula(formula, prover="z3")
    """
    from .proof_execution_engine import ProofExecutionEngine
    engine = ProofExecutionEngine(temp_dir=temp_dir, timeout=timeout)
    return engine.prove(formula, prover=prover)


def prove_with_all_provers(
    formula: "DeonticFormula",
    timeout: int = 60,
    temp_dir: Optional[str] = None
) -> List["ProofResult"]:
    """
    Try proving a formula with all available provers.
    
    Creates a ProofExecutionEngine and attempts to prove the formula
    using all installed and available theorem provers.
    
    Args:
        formula: Deontic formula to prove
        timeout: Timeout in seconds (default: 60)
        temp_dir: Optional temporary directory
        
    Returns:
        List of ProofResult objects, one per attempted prover
        
    Example:
        >>> formula = create_obligation("action", "entity")
        >>> results = prove_with_all_provers(formula)
        >>> successful = [r for r in results if r.status == ProofStatus.SUCCESS]
    """
    from .proof_execution_engine import ProofExecutionEngine
    engine = ProofExecutionEngine(temp_dir=temp_dir, timeout=timeout)
    return engine.prove_with_all_available_provers(formula)


def check_consistency(
    rule_set: "DeonticRuleSet",
    prover: str = "z3",
    timeout: int = 60,
    temp_dir: Optional[str] = None
) -> "ProofResult":
    """
    Quick consistency check for a deontic rule set.
    
    Creates a ProofExecutionEngine and checks if the given rule set
    is consistent (non-contradictory).
    
    Args:
        rule_set: DeonticRuleSet to check for consistency
        prover: Theorem prover to use (default: "z3")
        timeout: Timeout in seconds (default: 60)
        temp_dir: Optional temporary directory
        
    Returns:
        ProofResult indicating consistency status
        
    Example:
        >>> from ipfs_datasets_py.logic.integration.deontic_logic_core import DeonticRuleSet
        >>> rule_set = DeonticRuleSet()
        >>> # Add rules to rule_set
        >>> result = check_consistency(rule_set)
    """
    from .proof_execution_engine import ProofExecutionEngine
    engine = ProofExecutionEngine(temp_dir=temp_dir, timeout=timeout)
    return engine.check_consistency(rule_set, prover=prover)


def get_lean_template() -> str:
    """
    Get the Lean 4 proof template.
    
    Returns:
        Lean 4 template string for deontic logic proofs
        
    Example:
        >>> template = get_lean_template()
        >>> "Obligatory" in template
        True
    """
    return """-- Lean 4 proof for deontic logic formula
-- Auto-generated from IPFS Datasets Python

-- Define deontic modalities
def Obligatory (P : Prop) : Prop := P
def Permitted (P : Prop) : Prop := ¬¬P
def Forbidden (P : Prop) : Prop := ¬P

-- Define variables and predicates
{variables}

-- Statement to prove
def statement : Prop := {translation.translated_formula}

-- Theorem proving
theorem main : statement := by
  {proof_steps}
"""


def get_coq_template() -> str:
    """
    Get the Coq proof template.
    
    Returns:
        Coq template string for deontic logic proofs
        
    Example:
        >>> template = get_coq_template()
        >>> "Obligatory" in template
        True
    """
    return """(* Coq proof for deontic logic formula *)
(* Auto-generated from IPFS Datasets Python *)

(* Define deontic modalities *)
Definition Obligatory (P : Prop) : Prop := P.
Definition Permitted (P : Prop) : Prop := ~~P.
Definition Forbidden (P : Prop) : Prop := ~P.

(* Define variables and predicates *)
{variables}

(* Statement to prove *)
Definition statement : Prop := {translation.translated_formula}.

(* Theorem proving *)
Theorem main : statement.
Proof.
  {proof_steps}
Qed.
"""


# Export utility functions
__all__ = [
    'create_proof_engine',
    'prove_formula',
    'prove_with_all_provers',
    'check_consistency',
    'get_lean_template',
    'get_coq_template',
]
