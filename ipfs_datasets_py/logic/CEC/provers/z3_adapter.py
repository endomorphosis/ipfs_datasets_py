"""
Z3 SMT Solver Adapter for CEC (Phase 6 Week 1).

This module provides integration with the Z3 SMT (Satisfiability Modulo Theories)
solver for automated theorem proving in CEC logic.

Classes:
    Z3Adapter: Main adapter for Z3 solver
    Z3ProofResult: Result of Z3 proving attempt

Features:
    - DCEC to Z3 formula translation
    - SMT-based theorem proving
    - Model generation for satisfiable formulas
    - Unsat core extraction for unsatisfiable formulas
    - Timeout and resource limit configuration
    - Support for deontic, cognitive, and temporal operators

Usage:
    >>> from ipfs_datasets_py.logic.CEC.provers.z3_adapter import Z3Adapter
    >>> adapter = Z3Adapter()
    >>> from ipfs_datasets_py.logic.CEC.native.dcec_core import *
    >>> # Create formula
    >>> result = adapter.prove(formula, [axioms])
    >>> result.is_valid
    True
"""

from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

try:
    import z3
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False
    z3 = None

from ..native.dcec_core import (
    Formula,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    QuantifiedFormula,
    DeonticOperator,
    CognitiveOperator,
    TemporalOperator,
    LogicalConnective,
)

logger = logging.getLogger(__name__)


class ProofStatus(Enum):
    """Status of proof attempt."""
    VALID = "valid"                # Formula is provably true
    INVALID = "invalid"            # Formula is provably false
    SATISFIABLE = "satisfiable"    # Formula is satisfiable (may be true)
    UNSATISFIABLE = "unsatisfiable"  # Formula is unsatisfiable
    UNKNOWN = "unknown"            # Solver cannot determine
    ERROR = "error"                # Error during proving
    TIMEOUT = "timeout"            # Proof attempt timed out


@dataclass
class Z3ProofResult:
    """
    Result of Z3 proof attempt.
    
    Attributes:
        status: Proof status
        is_valid: Whether formula is provably valid
        model: Satisfying model (if satisfiable)
        unsat_core: Unsatisfiable core (if unsatisfiable)
        proof_time: Time taken for proof (seconds)
        error_message: Error message if failed
        
    Example:
        >>> result = Z3ProofResult(
        ...     status=ProofStatus.VALID,
        ...     is_valid=True,
        ...     proof_time=0.05
        ... )
    """
    status: ProofStatus
    is_valid: bool = False
    model: Optional[Any] = None
    unsat_core: List[Any] = field(default_factory=list)
    proof_time: float = 0.0
    error_message: Optional[str] = None
    z3_formula: Optional[Any] = None  # Z3 internal representation


class Z3Adapter:
    """
    Adapter for Z3 SMT solver.
    
    This class translates CEC formulas to Z3 format and uses Z3
    to perform automated theorem proving.
    
    Attributes:
        timeout: Timeout for proof attempts (milliseconds)
        max_memory: Maximum memory for Z3 (MB)
        
    Example:
        >>> adapter = Z3Adapter(timeout=5000)
        >>> result = adapter.prove(formula, axioms)
        >>> if result.is_valid:
        ...     print("Formula is valid!")
    """
    
    def __init__(
        self,
        timeout: int = 10000,
        max_memory: int = 1024
    ):
        """Initialize Z3 adapter.
        
        Args:
            timeout: Timeout in milliseconds (default: 10000)
            max_memory: Maximum memory in MB (default: 1024)
            
        Raises:
            ImportError: If Z3 is not installed
        """
        if not Z3_AVAILABLE:
            raise ImportError(
                "Z3 solver not available. Install with: pip install z3-solver"
            )
        
        self.timeout = timeout
        self.max_memory = max_memory
        self.solver = None
        self._init_solver()
        logger.info(f"Z3 adapter initialized (timeout={timeout}ms, memory={max_memory}MB)")
    
    def _init_solver(self) -> None:
        """Initialize Z3 solver with configuration."""
        self.solver = z3.Solver()
        
        # Set timeout
        self.solver.set("timeout", self.timeout)
        
        # Set memory limit
        self.solver.set("max_memory", self.max_memory)
    
    def reset(self) -> None:
        """Reset solver state."""
        self._init_solver()
    
    def translate_to_z3(self, formula: Formula) -> Any:
        """Translate CEC formula to Z3 formula.
        
        Args:
            formula: CEC Formula to translate
            
        Returns:
            Z3 formula representation
            
        Raises:
            NotImplementedError: For unsupported formula types
        """
        if isinstance(formula, AtomicFormula):
            return self._translate_atomic(formula)
        
        elif isinstance(formula, DeonticFormula):
            return self._translate_deontic(formula)
        
        elif isinstance(formula, CognitiveFormula):
            return self._translate_cognitive(formula)
        
        elif isinstance(formula, TemporalFormula):
            return self._translate_temporal(formula)
        
        elif isinstance(formula, ConnectiveFormula):
            return self._translate_connective(formula)
        
        elif isinstance(formula, QuantifiedFormula):
            return self._translate_quantified(formula)
        
        else:
            raise NotImplementedError(f"Unsupported formula type: {type(formula)}")
    
    def _translate_atomic(self, formula: AtomicFormula) -> Any:
        """Translate atomic formula to Z3.
        
        Args:
            formula: AtomicFormula to translate
            
        Returns:
            Z3 Bool constant
        """
        # Create Z3 boolean constant for predicate application
        pred_name = formula.predicate.name
        return z3.Bool(pred_name)
    
    def _translate_deontic(self, formula: DeonticFormula) -> Any:
        """Translate deontic formula to Z3.
        
        Deontic operators are encoded as modal operators in Z3.
        
        Args:
            formula: DeonticFormula to translate
            
        Returns:
            Z3 formula
        """
        # Translate inner formula
        inner_z3 = self.translate_to_z3(formula.formula)
        
        # Encode deontic operator
        # O(phi) = obligated(phi) - encoded as uninterpreted function
        # P(phi) = permitted(phi)
        # F(phi) = forbidden(phi) = ~P(phi)
        
        if formula.operator == DeonticOperator.OBLIGATION:
            # Create obligated predicate
            obligated = z3.Function('obligated', z3.BoolSort(), z3.BoolSort())
            return obligated(inner_z3)
        
        elif formula.operator == DeonticOperator.PERMISSION:
            # Create permitted predicate
            permitted = z3.Function('permitted', z3.BoolSort(), z3.BoolSort())
            return permitted(inner_z3)
        
        elif formula.operator == DeonticOperator.PROHIBITION:
            # Forbidden = NOT permitted
            permitted = z3.Function('permitted', z3.BoolSort(), z3.BoolSort())
            return z3.Not(permitted(inner_z3))
        
        else:
            raise NotImplementedError(f"Unsupported deontic operator: {formula.operator}")
    
    def _translate_cognitive(self, formula: CognitiveFormula) -> Any:
        """Translate cognitive formula to Z3.
        
        Args:
            formula: CognitiveFormula to translate
            
        Returns:
            Z3 formula
        """
        # Translate inner formula
        inner_z3 = self.translate_to_z3(formula.formula)
        
        # Encode cognitive operator as uninterpreted function
        if formula.operator == CognitiveOperator.BELIEF:
            believes = z3.Function('believes', z3.BoolSort(), z3.BoolSort())
            return believes(inner_z3)
        
        elif formula.operator == CognitiveOperator.KNOWLEDGE:
            knows = z3.Function('knows', z3.BoolSort(), z3.BoolSort())
            return knows(inner_z3)
        
        elif formula.operator == CognitiveOperator.INTENTION:
            intends = z3.Function('intends', z3.BoolSort(), z3.BoolSort())
            return intends(inner_z3)
        
        elif formula.operator == CognitiveOperator.DESIRE:
            desires = z3.Function('desires', z3.BoolSort(), z3.BoolSort())
            return desires(inner_z3)
        
        elif formula.operator == CognitiveOperator.GOAL:
            has_goal = z3.Function('has_goal', z3.BoolSort(), z3.BoolSort())
            return has_goal(inner_z3)
        
        else:
            raise NotImplementedError(f"Unsupported cognitive operator: {formula.operator}")
    
    def _translate_temporal(self, formula: TemporalFormula) -> Any:
        """Translate temporal formula to Z3.
        
        Args:
            formula: TemporalFormula to translate
            
        Returns:
            Z3 formula
        """
        # Translate inner formula
        inner_z3 = self.translate_to_z3(formula.formula)
        
        # Encode temporal operator
        if formula.operator == TemporalOperator.ALWAYS:
            always_op = z3.Function('always', z3.BoolSort(), z3.BoolSort())
            return always_op(inner_z3)
        
        elif formula.operator == TemporalOperator.EVENTUALLY:
            eventually_op = z3.Function('eventually', z3.BoolSort(), z3.BoolSort())
            return eventually_op(inner_z3)
        
        elif formula.operator == TemporalOperator.NEXT:
            next_op = z3.Function('next', z3.BoolSort(), z3.BoolSort())
            return next_op(inner_z3)
        
        else:
            raise NotImplementedError(f"Unsupported temporal operator: {formula.operator}")
    
    def _translate_connective(self, formula: ConnectiveFormula) -> Any:
        """Translate connective formula to Z3.
        
        Args:
            formula: ConnectiveFormula to translate
            
        Returns:
            Z3 formula
        """
        # Translate subformulas
        z3_formulas = [self.translate_to_z3(f) for f in formula.formulas]
        
        if formula.connective == LogicalConnective.AND:
            return z3.And(*z3_formulas)
        
        elif formula.connective == LogicalConnective.OR:
            return z3.Or(*z3_formulas)
        
        elif formula.connective == LogicalConnective.NOT:
            return z3.Not(z3_formulas[0])
        
        elif formula.connective == LogicalConnective.IMPLIES:
            return z3.Implies(z3_formulas[0], z3_formulas[1])
        
        elif formula.connective == LogicalConnective.IFF:
            return z3_formulas[0] == z3_formulas[1]
        
        else:
            raise NotImplementedError(f"Unsupported connective: {formula.connective}")
    
    def _translate_quantified(self, formula: QuantifiedFormula) -> Any:
        """Translate quantified formula to Z3.
        
        Args:
            formula: QuantifiedFormula to translate
            
        Returns:
            Z3 quantified formula
        """
        # Create Z3 variable
        var_name = formula.variable.name
        z3_var = z3.Const(var_name, z3.BoolSort())
        
        # Translate body
        body_z3 = self.translate_to_z3(formula.formula)
        
        # Create quantified formula
        if formula.quantifier == LogicalConnective.FORALL:
            return z3.ForAll([z3_var], body_z3)
        elif formula.quantifier == LogicalConnective.EXISTS:
            return z3.Exists([z3_var], body_z3)
        else:
            raise NotImplementedError(f"Unsupported quantifier: {formula.quantifier}")
    
    def prove(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]] = None,
        timeout_ms: Optional[int] = None
    ) -> Z3ProofResult:
        """Prove formula using Z3.
        
        Args:
            formula: Formula to prove
            axioms: Optional list of axioms
            timeout_ms: Optional timeout override (milliseconds)
            
        Returns:
            Z3ProofResult with proof status and details
        """
        import time
        start_time = time.time()
        
        try:
            # Reset solver
            self.reset()
            
            # Set custom timeout if provided
            if timeout_ms:
                self.solver.set("timeout", timeout_ms)
            
            # Add axioms to solver
            if axioms:
                for axiom in axioms:
                    z3_axiom = self.translate_to_z3(axiom)
                    self.solver.add(z3_axiom)
            
            # Translate formula
            z3_formula = self.translate_to_z3(formula)
            
            # To prove formula, check if NOT formula is unsatisfiable
            self.solver.add(z3.Not(z3_formula))
            
            # Check satisfiability
            check_result = self.solver.check()
            proof_time = time.time() - start_time
            
            if check_result == z3.unsat:
                # NOT formula is unsat, so formula is valid
                return Z3ProofResult(
                    status=ProofStatus.VALID,
                    is_valid=True,
                    proof_time=proof_time,
                    z3_formula=z3_formula
                )
            
            elif check_result == z3.sat:
                # NOT formula is sat, so formula is not valid
                # Get counterexample model
                model = self.solver.model()
                return Z3ProofResult(
                    status=ProofStatus.INVALID,
                    is_valid=False,
                    model=model,
                    proof_time=proof_time,
                    z3_formula=z3_formula
                )
            
            else:  # z3.unknown
                return Z3ProofResult(
                    status=ProofStatus.UNKNOWN,
                    is_valid=False,
                    proof_time=proof_time,
                    error_message="Z3 returned unknown",
                    z3_formula=z3_formula
                )
        
        except Exception as e:
            logger.error(f"Z3 proving error: {e}")
            return Z3ProofResult(
                status=ProofStatus.ERROR,
                is_valid=False,
                proof_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def check_satisfiability(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]] = None
    ) -> Z3ProofResult:
        """Check if formula is satisfiable.
        
        Args:
            formula: Formula to check
            axioms: Optional list of axioms
            
        Returns:
            Z3ProofResult with satisfiability status
        """
        import time
        start_time = time.time()
        
        try:
            # Reset solver
            self.reset()
            
            # Add axioms
            if axioms:
                for axiom in axioms:
                    z3_axiom = self.translate_to_z3(axiom)
                    self.solver.add(z3_axiom)
            
            # Add formula
            z3_formula = self.translate_to_z3(formula)
            self.solver.add(z3_formula)
            
            # Check satisfiability
            check_result = self.solver.check()
            proof_time = time.time() - start_time
            
            if check_result == z3.sat:
                model = self.solver.model()
                return Z3ProofResult(
                    status=ProofStatus.SATISFIABLE,
                    is_valid=False,
                    model=model,
                    proof_time=proof_time,
                    z3_formula=z3_formula
                )
            
            elif check_result == z3.unsat:
                return Z3ProofResult(
                    status=ProofStatus.UNSATISFIABLE,
                    is_valid=False,
                    proof_time=proof_time,
                    z3_formula=z3_formula
                )
            
            else:
                return Z3ProofResult(
                    status=ProofStatus.UNKNOWN,
                    is_valid=False,
                    proof_time=proof_time,
                    z3_formula=z3_formula
                )
        
        except Exception as e:
            logger.error(f"Z3 satisfiability check error: {e}")
            return Z3ProofResult(
                status=ProofStatus.ERROR,
                is_valid=False,
                proof_time=time.time() - start_time,
                error_message=str(e)
            )
    
    def get_model(self, formula: Formula) -> Optional[Any]:
        """Get satisfying model for formula.
        
        Args:
            formula: Formula to get model for
            
        Returns:
            Z3 model or None if unsatisfiable
        """
        result = self.check_satisfiability(formula)
        return result.model if result.status == ProofStatus.SATISFIABLE else None
    
    def is_available(self) -> bool:
        """Check if Z3 is available.
        
        Returns:
            True if Z3 is installed and working
        """
        return Z3_AVAILABLE and self.solver is not None


def check_z3_installation() -> bool:
    """Check if Z3 is properly installed.
    
    Returns:
        True if Z3 is available
    """
    return Z3_AVAILABLE


def get_z3_version() -> Optional[str]:
    """Get Z3 version string.
    
    Returns:
        Z3 version or None if not installed
    """
    if Z3_AVAILABLE:
        return z3.get_version_string()
    return None
